"""Tests for stale-while-revalidate snapshot serving on Find People."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.people import CompanyResponse, PersonResponse
from app.services.job_research_snapshot_service import (
    SNAPSHOT_FRESH_TTL,
    SNAPSHOT_MAX_SERVE_AGE,
    evict_person_from_job_research_snapshots,
    snapshot_serve_decision,
)
from app.services.people.serialize import snapshot_to_search_response


def _snapshot(*, total: int, age: timedelta | None, target: int = 5):
    updated = None if age is None else datetime.now(timezone.utc) - age
    return SimpleNamespace(
        total_candidates=total,
        target_count_per_bucket=target,
        updated_at=updated,
        created_at=updated,
    )


def _make_session(mock_db):
    class FakeSession:
        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, *args):
            return False

    return FakeSession()


# --- freshness decision -----------------------------------------------------

def test_decision_miss_when_no_snapshot():
    assert snapshot_serve_decision(None) == "miss"


def test_decision_miss_when_empty():
    # A snapshot with zero candidates must run live, not serve a blank result.
    assert snapshot_serve_decision(_snapshot(total=0, age=timedelta(minutes=5))) == "miss"


def test_decision_fresh_within_ttl():
    snap = _snapshot(total=6, age=SNAPSHOT_FRESH_TTL - timedelta(hours=1))
    assert snapshot_serve_decision(snap) == "fresh"


def test_decision_stale_past_ttl_within_max_age():
    snap = _snapshot(total=6, age=SNAPSHOT_FRESH_TTL + timedelta(hours=1))
    assert snapshot_serve_decision(snap) == "stale"


def test_decision_miss_past_max_age():
    snap = _snapshot(total=6, age=SNAPSHOT_MAX_SERVE_AGE + timedelta(days=1))
    assert snapshot_serve_decision(snap) == "miss"


def test_decision_miss_when_snapshot_was_generated_for_smaller_depth():
    snap = _snapshot(total=3, target=1, age=timedelta(minutes=5))

    assert snapshot_serve_decision(
        snap, requested_target_count_per_bucket=5
    ) == "miss"


@pytest.mark.asyncio
async def test_negative_feedback_evicts_person_from_all_snapshot_buckets():
    person_id = uuid.uuid4()
    snapshot = SimpleNamespace(
        recruiters=[{"id": str(person_id), "current_company_verified": True}],
        hiring_managers=[],
        peers=[{"id": str(uuid.uuid4())}],
        your_connections=[{"id": str(person_id)}],
        recruiter_count=1,
        manager_count=0,
        peer_count=1,
        warm_path_count=1,
        verified_count=1,
        total_candidates=2,
    )

    class _Scalars:
        def all(self):
            return [snapshot]

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Db:
        async def execute(self, _statement):
            return _Result()

    db = _Db()

    updated = await evict_person_from_job_research_snapshots(
        db, user_id=uuid.uuid4(), person_id=person_id
    )

    assert updated == 1
    assert snapshot.recruiters == []
    assert snapshot.your_connections == []
    assert snapshot.total_candidates == 1
    assert snapshot.verified_count == 0


# --- snapshot -> response reconstruction ------------------------------------

def _person_dict(company: CompanyResponse | None) -> dict:
    return PersonResponse(
        id=uuid.uuid4(),
        full_name="Jane Recruiter",
        title="Technical Recruiter",
        department=None,
        seniority=None,
        linkedin_url=None,
        github_url=None,
        work_email=None,
        email_verified=False,
        person_type="recruiter",
        profile_data=None,
        github_data=None,
        source="public_web",
        company=company,
    ).model_dump(mode="json")


def test_snapshot_to_response_round_trips_and_lifts_company():
    company = CompanyResponse(
        id=uuid.uuid4(),
        name="Stripe",
        domain="stripe.com",
        size=None,
        industry=None,
        description=None,
        careers_url=None,
    )
    snapshot = SimpleNamespace(
        recruiters=[_person_dict(company)],
        hiring_managers=[],
        peers=[_person_dict(None)],
        your_connections=[],
        errors=None,
    )

    response = snapshot_to_search_response(snapshot)

    assert response.served_from_snapshot is True
    assert len(response.recruiters) == 1
    assert len(response.peers) == 1
    # Top-level company is lifted from the first person that carries one.
    assert response.company is not None
    assert response.company.name == "Stripe"


# --- background refresh debounce --------------------------------------------

@pytest.mark.asyncio()
async def test_refresh_debounced_when_just_updated():
    """A snapshot refreshed seconds ago must not trigger another search."""
    from app.tasks.auto_prospect import _refresh_job_research_snapshot

    recent = SimpleNamespace(updated_at=datetime.now(timezone.utc) - timedelta(seconds=20))
    with (
        patch("app.tasks.auto_prospect.async_session", return_value=_make_session(AsyncMock())),
        patch(
            "app.services.job_research_snapshot_service.get_job_research_snapshot",
            new=AsyncMock(return_value=recent),
        ),
        patch("app.services.people.search_people_for_job", new=AsyncMock()) as mock_search,
    ):
        result = await _refresh_job_research_snapshot(uuid.uuid4(), uuid.uuid4())

    assert result["skipped"] is True
    assert result["refreshed"] is False
    mock_search.assert_not_awaited()


@pytest.mark.asyncio()
async def test_refresh_runs_and_saves_when_stale():
    """A snapshot older than the debounce window re-runs search and re-saves."""
    from app.tasks.auto_prospect import _refresh_job_research_snapshot

    old = SimpleNamespace(updated_at=datetime.now(timezone.utc) - timedelta(hours=2))
    fake_response = SimpleNamespace(
        recruiters=[], hiring_managers=[], peers=[], your_connections=[], errors=None,
    )
    with (
        patch("app.tasks.auto_prospect.async_session", return_value=_make_session(AsyncMock())),
        patch(
            "app.services.job_research_snapshot_service.get_job_research_snapshot",
            new=AsyncMock(return_value=old),
        ),
        patch(
            "app.services.people.search_people_for_job",
            new=AsyncMock(return_value={"company": SimpleNamespace(name="Stripe")}),
        ) as mock_search,
        patch(
            "app.services.people.serialize._serialize_people_search_result",
            return_value=fake_response,
        ),
        patch(
            "app.services.job_research_snapshot_service.save_job_research_snapshot",
            new=AsyncMock(),
        ) as mock_save,
    ):
        result = await _refresh_job_research_snapshot(uuid.uuid4(), uuid.uuid4())

    assert result["refreshed"] is True
    assert result["skipped"] is False
    mock_search.assert_awaited_once()
    mock_save.assert_awaited_once()
