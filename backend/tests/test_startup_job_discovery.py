from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.job import Job
from app.models.search_preference import SearchPreference
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


async def test_discover_jobs_startup_mode_persists_search_preference_with_startup_mode():
    """Saved-search refresh must know a query came from startup discover."""
    user_id = uuid.uuid4()
    profile = _make_profile("Product Manager")

    # db.execute is called for profile load, then for each
    # _ensure_startup_search_preferences existence check. Return profile
    # first, then None (no existing pref) for all subsequent lookups.
    db = MagicMock()
    profile_result = _ScalarResult(profile)
    missing_pref_result = _ScalarResult(None)
    db.execute = AsyncMock(side_effect=[profile_result] + [missing_pref_result] * 20)
    db.add = MagicMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.job_service.yc_jobs_client.search_yc_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.wellfound_jobs_client.search_wellfound_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.ventureloop_jobs_client.search_ventureloop_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.conviction_jobs_client.fetch_conviction_startups", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.speedrun_jobs_client.fetch_speedrun_companies", new_callable=AsyncMock, return_value=[]),
    ):
        await discover_jobs(db, user_id, queries=["founding engineer"], mode="startup")

    added_prefs = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and isinstance(call.args[0], SearchPreference)
    ]
    assert len(added_prefs) == 1
    assert added_prefs[0].query == "founding engineer"
    assert added_prefs[0].mode == "startup"


async def test_run_startup_refresh_for_query_returns_only_new_jobs():
    """Delta snapshot should pick up jobs created by the startup discover call."""
    from datetime import datetime, timezone

    from app.services import job_service as js

    user_id = uuid.uuid4()
    profile = _make_profile("Product Manager")

    # Simulated "newly created" job row returned by the post-snapshot query.
    new_job = MagicMock(spec=Job)
    new_job.id = uuid.uuid4()
    new_job.user_id = user_id
    new_job.created_at = datetime.now(timezone.utc)

    post_snapshot_result = _ScalarResult([new_job])

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult(profile), post_snapshot_result])
    db.commit = AsyncMock()

    with (
        patch.object(js, "_discover_startup_direct_sources", new=AsyncMock(return_value=1)),
        patch.object(js, "_discover_startup_ecosystems", new=AsyncMock(return_value=0)),
    ):
        jobs = await js.run_startup_refresh_for_query(db, user_id, "founding engineer")

    assert jobs == [new_job]


async def test_refresh_task_routes_startup_prefs_to_startup_refresh():
    """Celery refresh branches on SearchPreference.mode."""
    from app.tasks import jobs as jobs_task

    user_id = uuid.uuid4()

    default_pref = MagicMock()
    default_pref.query = "software engineer"
    default_pref.location = None
    default_pref.remote_only = False
    default_pref.mode = "default"

    startup_pref = MagicMock()
    startup_pref.query = "founding engineer"
    startup_pref.location = None
    startup_pref.remote_only = False
    startup_pref.mode = "startup"

    db = MagicMock()
    prefs_result = MagicMock()
    prefs_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[default_pref, startup_pref]))
    )
    starred_result = MagicMock()
    starred_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    db.execute = AsyncMock(side_effect=[prefs_result, starred_result])
    db.commit = AsyncMock()

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=db)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    search_mock = AsyncMock(return_value=[])
    startup_mock = AsyncMock(return_value=[])

    with (
        patch.object(jobs_task, "async_session", return_value=session_cm),
        patch.object(jobs_task, "search_jobs", new=search_mock),
        patch.object(jobs_task, "run_startup_refresh_for_query", new=startup_mock),
    ):
        await jobs_task._refresh_user_feeds(user_id)

    search_mock.assert_awaited_once()
    assert search_mock.await_args.kwargs["query"] == "software engineer"
    startup_mock.assert_awaited_once()
    assert startup_mock.await_args.kwargs["query"] == "founding engineer"


def test_infer_startup_tags_for_job_tags_known_startup_company():
    """A Greenhouse posting at a known-startup company should gain inferred tags."""
    from app.services.job_service import _infer_startup_tags_for_job

    data = {
        "company_name": "Cartesia",
        "title": "Backend Engineer",
        "source": "greenhouse",
        "tags": [],
    }
    _infer_startup_tags_for_job(data, known_startup_companies={"cartesia"})

    assert "startup" in data["tags"]
    assert "startup_source:inferred" in data["tags"]


def test_infer_startup_tags_for_job_skips_when_already_tagged_authoritatively():
    from app.services.job_service import _infer_startup_tags_for_job

    data = {
        "company_name": "Cartesia",
        "title": "PM",
        "tags": ["startup", "startup_source:yc_jobs"],
    }
    _infer_startup_tags_for_job(data, known_startup_companies={"cartesia"})

    # Untouched — authoritative source tag wins.
    assert data["tags"] == ["startup", "startup_source:yc_jobs"]


def test_infer_startup_tags_for_job_noop_for_unknown_company():
    from app.services.job_service import _infer_startup_tags_for_job

    data = {"company_name": "Megacorp", "title": "SWE", "tags": []}
    _infer_startup_tags_for_job(data, known_startup_companies={"cartesia"})
    assert data["tags"] == []
