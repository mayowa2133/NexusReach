"""Tests for per-job people pre-warm that makes opening a job instant.

Every newly discovered job is queued for a background people search and held
out of the feed (people_prewarm_status="pending") until it finishes, then
flipped to "ready". The search persists the top recruiter / hiring manager /
next-best contact and a snapshot so the People panel renders immediately.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _make_session(mock_db):
    class FakeSession:
        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, *args):
            return False

    return FakeSession()


class _FakePerson:
    """Stands in for a serialized PersonResponse (only model_dump is used)."""

    def model_dump(self, mode="json"):
        return {"id": "x"}


def _serialized(recruiters=1, hiring_managers=1, peers=1):
    return SimpleNamespace(
        recruiters=[_FakePerson() for _ in range(recruiters)],
        hiring_managers=[_FakePerson() for _ in range(hiring_managers)],
        peers=[_FakePerson() for _ in range(peers)],
        your_connections=[],
        errors=None,
    )


@pytest.mark.asyncio()
async def test_prewarm_job_persists_snapshot_and_reveals_job():
    """A successful pre-warm saves the snapshot and flips the job to ready."""
    from app.tasks.auto_prospect import _prewarm_job_people

    mock_db = AsyncMock()
    search_result = {"company": SimpleNamespace(name="Stripe")}
    with (
        patch("app.tasks.auto_prospect.async_session", return_value=_make_session(mock_db)),
        patch(
            "app.services.people.search_people_for_job",
            new=AsyncMock(return_value=search_result),
        ) as mock_search,
        patch(
            "app.services.people.serialize._serialize_people_search_result",
            return_value=_serialized(),
        ),
        patch(
            "app.services.job_research_snapshot_service.save_job_research_snapshot",
            new=AsyncMock(),
        ) as mock_save,
    ):
        result = await _prewarm_job_people(uuid.uuid4(), uuid.uuid4())

    assert result["people_found"] == 3  # 1 recruiter + 1 HM + 1 next-best
    assert result["snapshot_saved"] is True
    mock_search.assert_awaited_once()
    # Default pre-warm asks for one contact per bucket (top 3 overall).
    assert mock_search.await_args.kwargs["target_count_per_bucket"] == 1
    mock_save.assert_awaited_once()
    # The job is revealed: an UPDATE ran and was committed.
    assert mock_db.execute.await_count >= 1
    assert mock_db.commit.await_count >= 1


@pytest.mark.asyncio()
async def test_prewarm_job_reveals_even_when_search_fails():
    """Decision: show the job anyway. A failed search must still reveal it."""
    from app.tasks.auto_prospect import _prewarm_job_people

    mock_db = AsyncMock()
    with (
        patch("app.tasks.auto_prospect.async_session", return_value=_make_session(mock_db)),
        patch(
            "app.services.people.search_people_for_job",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ),
        patch(
            "app.services.job_research_snapshot_service.save_job_research_snapshot",
            new=AsyncMock(),
        ) as mock_save,
    ):
        result = await _prewarm_job_people(uuid.uuid4(), uuid.uuid4())

    assert result["snapshot_saved"] is False
    assert result["people_found"] == 0
    mock_save.assert_not_awaited()
    # The failed search transaction is rolled back, then the job is still
    # marked ready so it surfaces in the feed.
    mock_db.rollback.assert_awaited()
    assert mock_db.execute.await_count >= 1
    assert mock_db.commit.await_count >= 1


@pytest.mark.asyncio()
async def test_maybe_prewarm_marks_pending_and_queues_per_job():
    """Every new job is marked pending and gets its own pre-warm task."""
    from app.services.jobs import storage

    jobs = [
        SimpleNamespace(id=uuid.uuid4(), match_score=float(i), people_prewarm_status="ready")
        for i in range(3)
    ]
    user_id = uuid.uuid4()
    with (
        patch(
            "app.services.settings_service.is_people_prewarm_enabled",
            new=AsyncMock(return_value=True),
        ),
        patch("app.tasks.auto_prospect.prewarm_job_people") as mock_task,
    ):
        await storage._maybe_prewarm_people(AsyncMock(), user_id, jobs)

    assert mock_task.delay.call_count == 3
    assert all(job.people_prewarm_status == "pending" for job in jobs)
    queued_job_ids = {call.args[1] for call in mock_task.delay.call_args_list}
    assert queued_job_ids == {str(job.id) for job in jobs}
    # Every task is queued for this user.
    assert all(call.args[0] == str(user_id) for call in mock_task.delay.call_args_list)


@pytest.mark.asyncio()
async def test_maybe_prewarm_ranks_and_caps():
    """Highest-scored jobs warm first; the tail beyond the cap stays ready."""
    from app.services.jobs import storage

    jobs = [
        SimpleNamespace(id=uuid.uuid4(), match_score=score, people_prewarm_status="ready")
        for score in (10.0, 40.0, 20.0, 30.0)
    ]
    with (
        patch.object(storage, "PREWARM_MAX_JOBS_PER_BATCH", 2),
        patch(
            "app.services.settings_service.is_people_prewarm_enabled",
            new=AsyncMock(return_value=True),
        ),
        patch("app.tasks.auto_prospect.prewarm_job_people") as mock_task,
    ):
        await storage._maybe_prewarm_people(AsyncMock(), uuid.uuid4(), jobs)

    assert mock_task.delay.call_count == 2
    # The two top-scored jobs (40.0, 30.0) are pending; the rest remain ready.
    pending = {job.match_score for job in jobs if job.people_prewarm_status == "pending"}
    assert pending == {40.0, 30.0}
    ready = {job.match_score for job in jobs if job.people_prewarm_status == "ready"}
    assert ready == {10.0, 20.0}


def test_get_jobs_hides_pending_until_reveal_timeout():
    """The feed query must gate out jobs whose people pre-warm is still running."""
    import inspect

    from app.services.jobs import command_center

    src = inspect.getsource(command_center.get_jobs)
    # A pending job is hidden unless it has aged past the reveal cutoff.
    assert 'people_prewarm_status != "pending"' in src
    assert "reveal_cutoff" in src
    assert "Job.created_at <= reveal_cutoff" in src
    # The timeout is a bounded safety valve, not indefinite.
    assert command_center.PEOPLE_PREWARM_REVEAL_TIMEOUT.total_seconds() > 0


@pytest.mark.asyncio()
async def test_maybe_prewarm_respects_opt_out():
    """When the user disables pre-warm, no tasks are queued and nothing is gated."""
    from app.services.jobs import storage

    jobs = [
        SimpleNamespace(id=uuid.uuid4(), match_score=1.0, people_prewarm_status="ready")
    ]
    with (
        patch(
            "app.services.settings_service.is_people_prewarm_enabled",
            new=AsyncMock(return_value=False),
        ),
        patch("app.tasks.auto_prospect.prewarm_job_people") as mock_task,
    ):
        await storage._maybe_prewarm_people(AsyncMock(), uuid.uuid4(), jobs)

    mock_task.delay.assert_not_called()
    # Opt-out leaves jobs visible immediately.
    assert jobs[0].people_prewarm_status == "ready"
