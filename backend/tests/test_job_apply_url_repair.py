from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.job_service import _repair_missing_apply_urls


@pytest.mark.asyncio
async def test_repair_missing_apply_urls_updates_saved_dice_jobs():
    dice_job = MagicMock()
    dice_job.source = "dice"
    dice_job.url = "https://www.dice.com/job-detail/example"
    dice_job.apply_url = None

    other_job = MagicMock()
    other_job.source = "jsearch"
    other_job.url = "https://example.com/job"
    other_job.apply_url = None

    db = MagicMock()
    db.commit = AsyncMock()

    with patch(
        "app.services.job_service.remote_jobs_client.resolve_dice_apply_urls",
        new_callable=AsyncMock,
        return_value={
            dice_job.url: "https://careers.example.com/jobs/example/apply",
        },
    ) as mock_resolve:
        await _repair_missing_apply_urls(db, [dice_job, other_job])

    mock_resolve.assert_awaited_once_with([dice_job.url])
    assert dice_job.apply_url == "https://careers.example.com/jobs/example/apply"
    # Non-dice/newgrad rows are no longer persisted on the read path — _to_response
    # serves `apply_url or url`, so the feed GET doesn't dirty every row.
    assert other_job.apply_url is None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_repair_missing_apply_urls_updates_newgrad_and_simplify_jobs():
    newgrad_job = MagicMock()
    newgrad_job.source = "newgrad_jobs"
    newgrad_job.url = "https://www.newgrad-jobs.com/list-software-engineer-jobs/example"
    newgrad_job.apply_url = None

    simplify_job = MagicMock()
    simplify_job.source = "simplify_github"
    simplify_job.url = "https://jobs.example.com/new-grad-engineer"
    simplify_job.apply_url = None

    db = MagicMock()
    db.commit = AsyncMock()

    with (
        patch(
            "app.services.job_service.remote_jobs_client.resolve_dice_apply_urls",
            new_callable=AsyncMock,
        ) as mock_dice_resolve,
        patch(
            "app.services.job_service.newgrad_jobs_client.resolve_newgrad_apply_urls",
            new_callable=AsyncMock,
            return_value={
                newgrad_job.url: "https://careers.example.com/jobs/new-grad-engineer",
            },
        ) as mock_newgrad_resolve,
    ):
        await _repair_missing_apply_urls(db, [newgrad_job, simplify_job])

    mock_dice_resolve.assert_not_awaited()
    mock_newgrad_resolve.assert_awaited_once_with([newgrad_job.url])
    assert newgrad_job.apply_url == "https://careers.example.com/jobs/new-grad-engineer"
    # simplify rows are served via `apply_url or url` in _to_response, not persisted here.
    assert simplify_job.apply_url is None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_repair_missing_apply_urls_no_commit_when_nothing_resolved():
    """No resolved dice/newgrad URL -> nothing persisted and no commit.

    The plain url fallback is served by ``_to_response`` (``apply_url or url``),
    so the read path stays free of the large per-row UPDATE + commit that could
    invalidate the connection, expire the loaded rows, and 500 serialization with
    MissingGreenlet.
    """
    dice_job = MagicMock()
    dice_job.source = "dice"
    dice_job.url = "https://www.dice.com/job-detail/example"
    dice_job.apply_url = None

    db = MagicMock()
    db.commit = AsyncMock()

    with patch(
        "app.services.job_service.remote_jobs_client.resolve_dice_apply_urls",
        new_callable=AsyncMock,
        return_value={},
    ):
        await _repair_missing_apply_urls(db, [dice_job])

    assert dice_job.apply_url is None
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_apply_url_repair_enqueues_debounced_task():
    """dice/newgrad rows missing apply_url queue one background repair task."""
    import uuid

    from app.services.jobs import search as search_mod

    dice_job = MagicMock()
    dice_job.id = uuid.uuid4()
    dice_job.source = "dice"
    dice_job.url = "https://www.dice.com/job-detail/example"
    dice_job.apply_url = None

    covered_job = MagicMock()
    covered_job.id = uuid.uuid4()
    covered_job.source = "dice"
    covered_job.url = "https://www.dice.com/job-detail/other"
    covered_job.apply_url = "https://careers.example.com/apply"

    user_id = uuid.uuid4()
    with (
        patch(
            "app.clients.search_cache_client.acquire_debounce",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_debounce,
        patch("app.tasks.jobs.repair_job_apply_urls") as mock_task,
    ):
        queued = await search_mod.queue_apply_url_repair(user_id, [dice_job, covered_job])

    assert queued is True
    mock_debounce.assert_awaited_once()
    mock_task.delay.assert_called_once_with(str(user_id), [str(dice_job.id)])


@pytest.mark.asyncio
async def test_queue_apply_url_repair_skips_without_candidates_or_debounce():
    import uuid

    from app.services.jobs import search as search_mod

    other_job = MagicMock()
    other_job.id = uuid.uuid4()
    other_job.source = "jsearch"
    other_job.url = "https://example.com/job"
    other_job.apply_url = None

    user_id = uuid.uuid4()
    # No dice/newgrad candidates -> no debounce read, no task.
    with (
        patch(
            "app.clients.search_cache_client.acquire_debounce",
            new_callable=AsyncMock,
        ) as mock_debounce,
        patch("app.tasks.jobs.repair_job_apply_urls") as mock_task,
    ):
        assert await search_mod.queue_apply_url_repair(user_id, [other_job]) is False
    mock_debounce.assert_not_awaited()
    mock_task.delay.assert_not_called()

    dice_job = MagicMock()
    dice_job.id = uuid.uuid4()
    dice_job.source = "dice"
    dice_job.url = "https://www.dice.com/job-detail/example"
    dice_job.apply_url = None

    # Debounce held (or Redis down, which reads as held) -> no task.
    with (
        patch(
            "app.clients.search_cache_client.acquire_debounce",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("app.tasks.jobs.repair_job_apply_urls") as mock_task,
    ):
        assert await search_mod.queue_apply_url_repair(user_id, [dice_job]) is False
    mock_task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_queue_apply_url_repair_fails_soft_when_broker_down():
    """A broker outage must never break the feed read that queues the repair."""
    import uuid

    from app.services.jobs import search as search_mod

    dice_job = MagicMock()
    dice_job.id = uuid.uuid4()
    dice_job.source = "dice"
    dice_job.url = "https://www.dice.com/job-detail/example"
    dice_job.apply_url = None

    with (
        patch(
            "app.clients.search_cache_client.acquire_debounce",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.tasks.jobs.repair_job_apply_urls") as mock_task,
    ):
        mock_task.delay.side_effect = RuntimeError("broker down")
        assert await search_mod.queue_apply_url_repair(uuid.uuid4(), [dice_job]) is False
