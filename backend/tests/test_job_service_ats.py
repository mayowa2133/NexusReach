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
        if isinstance(self._value, list):
            return self._value[0] if len(self._value) == 1 else None
        return self._value

    def scalars(self):
        value = self._value

        class _Scalars:
            def __init__(self, raw):
                self._raw = raw

            def first(self):
                if isinstance(self._raw, list):
                    return self._raw[0] if self._raw else None
                return self._raw

            def all(self):
                if isinstance(self._raw, list):
                    return self._raw
                return [] if self._raw is None else [self._raw]

        return _Scalars(value)


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
    db.execute = AsyncMock(return_value=_ScalarResult(None))
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
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch(
        "app.services.job_service.ats_client.search_greenhouse",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = []
        await search_ats_jobs(db, user_id, "affirm", "greenhouse", limit=5)

    mock_search.assert_awaited_once_with("affirm", 5)


async def test_search_ats_jobs_reuses_existing_external_id_without_error():
    user_id = uuid.uuid4()
    existing_job = MagicMock()
    existing_job.id = uuid.uuid4()
    existing_job.external_id = "ashby_123"
    existing_job.url = "https://jobs.ashbyhq.com/zip/b261b0d9-bebd-4da1-a3b9-7a674f0616ac"
    existing_job.title = "Software Engineer, New Grad (2026 Start)"

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),
            _ScalarResult([existing_job, MagicMock()]),
        ]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch(
        "app.services.job_service.ats_client.search_ashby",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = [
            {
                "external_id": "ashby_123",
                "title": "Software Engineer, New Grad (2026 Start)",
                "company_name": "Zip",
                "location": "San Francisco, CA",
                "remote": False,
                "url": "https://jobs.ashbyhq.com/zip/b261b0d9-bebd-4da1-a3b9-7a674f0616ac?utm_source=jobboard",
                "description": "Join Zip as a new grad engineer.",
                "source": "ashby",
                "ats": "ashby",
                "ats_slug": "zip",
            }
        ]
        jobs = await search_ats_jobs(
            db,
            user_id,
            "zip",
            "ashby",
            job_url="https://jobs.ashbyhq.com/zip/b261b0d9-bebd-4da1-a3b9-7a674f0616ac",
        )

    assert jobs == [existing_job]
    db.add.assert_not_called()
