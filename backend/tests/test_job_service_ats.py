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

    adapter = MagicMock()
    adapter.search_board = AsyncMock(return_value=raw_jobs)
    adapter.fetch_exact = None

    with patch("app.services.job_service.ats_client.get_adapter", return_value=adapter):
        jobs = await search_ats_jobs(db, user_id, "affirm", "greenhouse")

    adapter.search_board.assert_awaited_once_with("affirm", None)
    assert len(jobs) == 25
    assert jobs[-1].title == "Role 24"


async def test_search_ats_jobs_passes_explicit_limit_through():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    adapter = MagicMock()
    adapter.search_board = AsyncMock(return_value=[])
    adapter.fetch_exact = None

    with patch("app.services.job_service.ats_client.get_adapter", return_value=adapter):
        await search_ats_jobs(db, user_id, "affirm", "greenhouse", limit=5)

    adapter.search_board.assert_awaited_once_with("affirm", 5)


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

    adapter = MagicMock()
    adapter.fetch_exact = None
    adapter.search_board = AsyncMock(
        return_value=[
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
    )
    with patch("app.services.job_service.ats_client.get_adapter", return_value=adapter):
        jobs = await search_ats_jobs(
            db,
            user_id,
            "zip",
            "ashby",
            job_url="https://jobs.ashbyhq.com/zip/b261b0d9-bebd-4da1-a3b9-7a674f0616ac",
        )

    assert jobs == [existing_job]
    db.add.assert_not_called()
    adapter.search_board.assert_awaited_once_with("zip", None)


async def test_search_ats_jobs_dispatches_workable_exact_job_lookup():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    workable_job = {
        "external_id": "wk_11DC4EA360",
        "title": "Software Engineer - Early Career (USA)",
        "company_name": "Trexquant Investment",
        "location": "Stamford, Connecticut, United States",
        "remote": False,
        "url": "https://apply.workable.com/trexquant/j/11DC4EA360",
        "description": "<p>Build systems</p>",
        "source": "workable",
        "ats": "workable",
        "ats_slug": "trexquant",
        "department": "Technology",
        "posted_at": "2025-09-09T00:00:00.000Z",
    }

    adapter = MagicMock()
    adapter.fetch_exact = AsyncMock()
    adapter.search_board = None

    with (
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch(
            "app.services.job_service.ats_client.fetch_exact_job",
            new_callable=AsyncMock,
        ) as mock_fetch_exact,
    ):
        mock_fetch_exact.return_value = [workable_job]
        jobs = await search_ats_jobs(
            db,
            user_id,
            None,
            None,
            job_url="https://apply.workable.com/trexquant/j/AC6E22F084/?jr_id=68c040328e65e77df55bf6c3",
        )

    mock_fetch_exact.assert_awaited_once()
    assert len(jobs) == 1
    assert jobs[0].ats == "workable"
    assert jobs[0].title == "Software Engineer - Early Career (USA)"


async def test_search_ats_jobs_dispatches_apple_exact_job_lookup():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    adapter = MagicMock()
    adapter.fetch_exact = AsyncMock()
    adapter.search_board = None
    apple_job = {
        "external_id": "apple_200652765",
        "title": "Software Engineer - Core OS Telemetry",
        "company_name": "Apple",
        "location": "Cupertino, California, United States",
        "remote": False,
        "url": "https://jobs.apple.com/en-us/details/200652765/software-engineer-core-os-telemetry",
        "description": "Build telemetry systems.",
        "source": "apple_jobs",
        "ats": "apple_jobs",
        "ats_slug": "apple",
        "posted_at": "2026-03-20T00:00:00Z",
    }

    with (
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch(
            "app.services.job_service.ats_client.fetch_exact_job",
            new_callable=AsyncMock,
        ) as mock_fetch_exact,
    ):
        mock_fetch_exact.return_value = [apple_job]
        jobs = await search_ats_jobs(
            db,
            user_id,
            None,
            None,
            job_url="https://jobs.apple.com/en-us/details/200652765/software-engineer-core-os-telemetry?board_id=17682",
        )

    mock_fetch_exact.assert_awaited_once()
    assert len(jobs) == 1
    assert jobs[0].ats == "apple_jobs"
    assert jobs[0].title == "Software Engineer - Core OS Telemetry"


async def test_search_ats_jobs_dispatches_workday_exact_job_lookup():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    adapter = MagicMock()
    adapter.fetch_exact = AsyncMock()
    adapter.search_board = None
    workday_job = {
        "external_id": "wd_JR2015144-1",
        "title": "Senior Systems Software Engineer - New College Grad 2026",
        "company_name": "NVIDIA",
        "location": "Hillsboro, OR, United States",
        "remote": False,
        "url": (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/"
            "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
        ),
        "description": "Build software systems.",
        "source": "workday",
        "ats": "workday",
        "ats_slug": "nvidia",
        "posted_at": "2026-03-20",
    }

    with (
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch(
            "app.services.job_service.ats_client.fetch_exact_job",
            new_callable=AsyncMock,
        ) as mock_fetch_exact,
    ):
        mock_fetch_exact.return_value = [workday_job]
        jobs = await search_ats_jobs(
            db,
            user_id,
            None,
            None,
            job_url=(
                "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
                "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
                "?jr_id=69bd8442b106024562826cc8"
            ),
        )

    mock_fetch_exact.assert_awaited_once()
    assert len(jobs) == 1
    assert jobs[0].ats == "workday"
    assert jobs[0].title == "Senior Systems Software Engineer - New College Grad 2026"


async def test_search_ats_jobs_refreshes_existing_exact_job_metadata():
    user_id = uuid.uuid4()
    existing_job = MagicMock()
    existing_job.id = uuid.uuid4()
    existing_job.external_id = "wd_JR100020"
    existing_job.url = (
        "https://fortune.wd108.myworkdayjobs.com/en-US/Fortune/job/Full-Stack-Software-Engineer-Nextjs_JR100020"
    )
    existing_job.title = "Full Stack Software Engineer Next.js"
    existing_job.company_name = "Fortune"
    existing_job.location = "New York City, United States"
    existing_job.remote = False
    existing_job.description = "Old description"
    existing_job.source = "workday"
    existing_job.ats = "workday"
    existing_job.ats_slug = "fortune"
    existing_job.department = None
    existing_job.employment_type = None

    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    adapter = MagicMock()
    adapter.fetch_exact = AsyncMock()
    adapter.search_board = None
    refreshed_job = {
        "external_id": "wd_JR100020",
        "title": "Full Stack Software Engineer Next.js",
        "company_name": "Fortune Media",
        "location": "New York City, United States",
        "remote": False,
        "url": "https://fortune.wd108.myworkdayjobs.com/en-US/Fortune/job/Full-Stack-Software-Engineer-Nextjs_JR100020",
        "description": "At Fortune Media, we are reinventing digital business journalism.",
        "source": "workday",
        "ats": "workday",
        "ats_slug": "fortune",
        "employment_type": "FULL_TIME",
    }

    with (
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch(
            "app.services.job_service.ats_client.fetch_exact_job",
            new_callable=AsyncMock,
            return_value=[refreshed_job],
        ),
        patch(
            "app.services.job_service._find_existing_job",
            new_callable=AsyncMock,
            return_value=existing_job,
        ),
    ):
        jobs = await search_ats_jobs(
            db,
            user_id,
            None,
            None,
            job_url=(
                "https://fortune.wd108.myworkdayjobs.com/en-US/Fortune/job/New-York-City/"
                "Full-Stack-Software-Engineer-Nextjs_JR100020?source=LinkedIn"
            ),
        )

    assert jobs == [existing_job]
    assert existing_job.company_name == "Fortune Media"
    assert existing_job.description == "At Fortune Media, we are reinventing digital business journalism."
    db.add.assert_not_called()


async def test_search_ats_jobs_dispatches_generic_exact_job_lookup():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    adapter = MagicMock()
    adapter.fetch_exact = AsyncMock()
    adapter.search_board = None
    generic_job = {
        "external_id": None,
        "title": "Platform Engineer",
        "company_name": "Example",
        "location": "Toronto, ON, CA",
        "remote": False,
        "url": "https://careers.example.com/jobs/platform-engineer",
        "description": "Build systems.",
        "source": "example_jobs",
        "ats": "example_jobs",
        "ats_slug": "example",
    }

    with (
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch(
            "app.services.job_service.ats_client.fetch_exact_job",
            new_callable=AsyncMock,
        ) as mock_fetch_exact,
    ):
        mock_fetch_exact.return_value = [generic_job]
        jobs = await search_ats_jobs(
            db,
            user_id,
            None,
            None,
            job_url="https://careers.example.com/jobs/platform-engineer?utm_source=test",
        )

    mock_fetch_exact.assert_awaited_once()
    assert len(jobs) == 1
    assert jobs[0].ats == "example_jobs"
    assert jobs[0].company_name == "Example"


async def test_search_ats_jobs_allows_exact_job_without_location():
    user_id = uuid.uuid4()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    adapter = MagicMock()
    adapter.fetch_exact = AsyncMock()
    adapter.search_board = None
    workday_job = {
        "external_id": "wd_JR2015144-1",
        "title": "Senior Systems Software Engineer - New College Grad 2026",
        "company_name": "NVIDIA",
        "location": None,
        "remote": False,
        "url": (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/"
            "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
        ),
        "description": "Build software systems.",
        "source": "workday",
        "ats": "workday",
        "ats_slug": "nvidia",
    }

    with (
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch(
            "app.services.job_service.ats_client.fetch_exact_job",
            new_callable=AsyncMock,
        ) as mock_fetch_exact,
    ):
        mock_fetch_exact.return_value = [workday_job]
        jobs = await search_ats_jobs(
            db,
            user_id,
            None,
            None,
            job_url=(
                "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
                "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
            ),
        )

    mock_fetch_exact.assert_awaited_once()
    assert len(jobs) == 1
    assert jobs[0].location is None
