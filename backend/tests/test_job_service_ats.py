"""Unit tests for ATS job ingestion defaults."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.job_service import search_ats_jobs

pytestmark = pytest.mark.asyncio


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _raw_job(index: int) -> dict:
    return {
        "external_id": f"gh_{index}",
        "title": f"Role {index}",
        "company_name": "Affirm",
        "location": "Remote",
        "remote": True,
        "url": f"https://example.com/{index}",
        "description": f"Description {index}",
        "source": "greenhouse",
        "ats": "greenhouse",
        "ats_slug": "affirm",
        "posted_at": "2026-03-18",
    }


async def test_search_ats_jobs_fetches_full_board_by_default():
    user_id = uuid.uuid4()
    raw_jobs = [_raw_job(index) for index in range(25)]
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_ScalarResult(None)] + [_ScalarResult(None) for _ in raw_jobs]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch(
        "app.services.job_service.ats_client.search_greenhouse",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = raw_jobs
        jobs = await search_ats_jobs(db, user_id, "affirm", "greenhouse")

    mock_search.assert_awaited_once_with("affirm", None)
    assert len(jobs) == 25
    assert jobs[-1].title == "Role 24"


async def test_search_ats_jobs_passes_explicit_limit_through():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult(None)])
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch(
        "app.services.job_service.ats_client.search_greenhouse",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = []
        await search_ats_jobs(db, user_id, "affirm", "greenhouse", limit=5)

    mock_search.assert_awaited_once_with("affirm", 5)
