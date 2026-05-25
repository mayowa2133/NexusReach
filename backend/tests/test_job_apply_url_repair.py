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
    assert other_job.apply_url == "https://example.com/job"
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
    assert simplify_job.apply_url == "https://jobs.example.com/new-grad-engineer"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_repair_missing_apply_urls_falls_back_to_source_url_when_no_direct_url_found():
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

    assert dice_job.apply_url == "https://www.dice.com/job-detail/example"
    db.commit.assert_awaited_once()
