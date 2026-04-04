from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.job import Job
from app.services.job_service import discover_jobs, search_ats_jobs

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


def _make_profile(*roles: str):
    profile = MagicMock()
    profile.target_roles = list(roles)
    profile.target_industries = ["Technology"]
    profile.target_locations = ["Remote", "San Francisco"]
    profile.resume_parsed = {"skills": ["Python", "TypeScript"]}
    return profile


def _startup_job(**overrides) -> dict:
    data = {
        "external_id": "yc_101",
        "title": "Product Manager",
        "company_name": "Cartesia",
        "location": "Remote (US)",
        "remote": True,
        "url": "https://www.ycombinator.com/companies/cartesia/jobs/101-product-manager",
        "description": "Own startup product discovery",
        "employment_type": "full-time",
        "posted_at": "2026-04-03T00:00:00Z",
        "source": "yc_jobs",
        "tags": ["startup", "startup_source:yc_jobs"],
    }
    data.update(overrides)
    return data


def _ats_job(**overrides) -> dict:
    data = {
        "external_id": "ab_123",
        "title": "Founding Engineer",
        "company_name": "Cartesia",
        "location": "San Francisco, CA",
        "remote": False,
        "url": "https://jobs.ashbyhq.com/cartesia/123",
        "description": "Build core product systems.",
        "source": "ashby",
        "ats": "ashby",
        "ats_slug": "cartesia",
        "posted_at": "2026-04-03T00:00:00Z",
    }
    data.update(overrides)
    return data


async def test_discover_jobs_startup_mode_stores_tagged_direct_board_jobs():
    user_id = uuid.uuid4()
    profile = _make_profile("Product Manager")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(profile))
    db.add = MagicMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.job_service.yc_jobs_client.search_yc_jobs", new_callable=AsyncMock, return_value=[
            _startup_job(),
            _startup_job(
                external_id="yc_102",
                title="Backend Engineer",
                url="https://www.ycombinator.com/companies/cartesia/jobs/102-backend-engineer",
            ),
        ]),
        patch("app.services.job_service.wellfound_jobs_client.search_wellfound_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.ventureloop_jobs_client.search_ventureloop_jobs", new_callable=AsyncMock, return_value=[
            _startup_job(
                external_id="ventureloop_1",
                title="Lead Product Manager",
                source="ventureloop",
                tags=["startup", "startup_source:ventureloop"],
                url="https://www.ventureloop.com/ventureloop/jobdetail.php?jobid=1",
                remote=False,
                location="San Francisco, CA, US",
            ),
        ]),
        patch("app.services.job_service.conviction_jobs_client.fetch_conviction_startups", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.speedrun_jobs_client.fetch_speedrun_companies", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service._find_existing_job", new_callable=AsyncMock, return_value=None),
    ):
        total_new = await discover_jobs(db, user_id, mode="startup")

    assert total_new == 2
    added_jobs = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and isinstance(call.args[0], Job)
    ]
    assert len(added_jobs) == 2
    assert all("startup" in (job.tags or []) for job in added_jobs)
    assert any("startup_source:yc_jobs" in (job.tags or []) for job in added_jobs)
    assert any("startup_source:ventureloop" in (job.tags or []) for job in added_jobs)


async def test_discover_jobs_startup_mode_resolves_speedrun_company_to_ats_board():
    user_id = uuid.uuid4()
    profile = _make_profile("Founding Engineer")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(profile))
    db.add = MagicMock()
    db.commit = AsyncMock()

    homepage = {
        "url": "https://cartesia.ai",
        "html": '<html><body><a href="https://jobs.ashbyhq.com/cartesia">Careers</a></body></html>',
    }
    adapter = MagicMock()
    adapter.search_board = AsyncMock(return_value=[_ats_job()])
    adapter.fetch_exact = None

    with (
        patch("app.services.job_service.yc_jobs_client.search_yc_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.wellfound_jobs_client.search_wellfound_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.ventureloop_jobs_client.search_ventureloop_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.conviction_jobs_client.fetch_conviction_startups", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.services.job_service.speedrun_jobs_client.fetch_speedrun_companies",
            new_callable=AsyncMock,
            return_value=[{"company_name": "Cartesia", "website_url": "https://cartesia.ai"}],
        ),
        patch("app.services.job_service.public_page_client.fetch_direct_page", new_callable=AsyncMock, return_value=homepage),
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch("app.services.job_service._find_existing_job", new_callable=AsyncMock, return_value=None),
    ):
        total_new = await discover_jobs(db, user_id, mode="startup")

    assert total_new == 1
    added_jobs = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and isinstance(call.args[0], Job)
    ]
    assert len(added_jobs) == 1
    assert added_jobs[0].source == "ashby"
    assert "startup_source:a16z_speedrun" in (added_jobs[0].tags or [])


async def test_search_ats_jobs_merges_startup_tags_into_existing_job():
    user_id = uuid.uuid4()
    existing_job = MagicMock()
    existing_job.id = uuid.uuid4()
    existing_job.tags = None
    existing_job.external_id = "ab_123"
    existing_job.title = "Founding Engineer"
    existing_job.url = "https://jobs.ashbyhq.com/corridor/123"

    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()

    adapter = MagicMock()
    adapter.search_board = AsyncMock(return_value=[_ats_job(company_name="Corridor", ats_slug="corridor")])
    adapter.fetch_exact = None

    with (
        patch("app.services.job_service.ats_client.get_adapter", return_value=adapter),
        patch("app.services.job_service._find_existing_job", new_callable=AsyncMock, return_value=existing_job),
    ):
        await search_ats_jobs(
            db,
            user_id,
            company_slug="corridor",
            ats_type="ashby",
            extra_tags=["startup", "startup_source:conviction"],
        )

    assert existing_job.tags == ["startup", "startup_source:conviction"]
    db.add.assert_not_called()
