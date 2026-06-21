import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.job import Job
from app.services.job_service import (
    _find_existing_job,
    _store_raw_jobs,
    discover_jobs,
    mark_stale_jobs_for_user,
    search_jobs,
    store_curated_ats_payloads_for_user,
)
from app.services.newgrad_jobs_backfill_service import backfill_newgrad_jobs

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


def _make_profile():
    profile = MagicMock()
    profile.target_roles = ["Software Engineer"]
    profile.target_industries = ["Technology"]
    profile.target_locations = ["Minneapolis", "Remote"]
    profile.resume_parsed = {"skills": ["Python", "Docker", "React"]}
    return profile


def _newgrad_job(**overrides) -> dict:
    data = {
        "external_id": "newgrad_associate_software_engineer_iam_automation_at_u_s_bank_21643587",
        "title": "Associate Software Engineer – IAM Automation",
        "company_name": "U.S. Bank",
        "location": "Minneapolis, MN",
        "remote": False,
        "url": "https://www.newgrad-jobs.com/list-software-engineer-jobs/associate_software_engineer_iam_automation_at_u_s_bank_21643587",
        "apply_url": "https://careers.usbank.com/associate-software-engineer",
        "description": "<div class='rich-text-block-20 w-richtext'><p>Build backend services with Python and Docker.</p></div>",
        "employment_type": "full-time",
        "salary_min": 93000.0,
        "salary_max": 109000.0,
        "salary_currency": "USD",
        "posted_at": "2026-04-04T00:00:00+00:00",
        "source": "newgrad_jobs",
        "level_label": "Entry Level",
    }
    data.update(overrides)
    return data


async def test_search_jobs_persists_enriched_newgrad_metadata():
    user_id = uuid.uuid4()
    profile = _make_profile()
    db = MagicMock()
    # Order: profile load, known-startup company scan (empty), pref upsert check.
    db.execute = AsyncMock(
        side_effect=[_ScalarResult(profile), _ScalarResult([]), _ScalarResult(None)]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.job_service.jsearch_client.search_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.adzuna_client.search_jobs", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.remote_jobs_client.search_remotive", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.remote_jobs_client.search_jobicy", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.remote_jobs_client.search_dice", new_callable=AsyncMock, return_value=[]),
        patch("app.services.job_service.remote_jobs_client.fetch_simplify_jobs", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.services.job_service.newgrad_jobs_client.search_newgrad_jobs",
            new_callable=AsyncMock,
            return_value=[_newgrad_job()],
        ),
        patch("app.services.jobs.storage._find_existing_job", new_callable=AsyncMock, return_value=None),
    ):
        jobs = await search_jobs(db, user_id, query="software engineer", sources=["newgrad"])

    assert len(jobs) == 1
    job = jobs[0]
    assert job.location == "Minneapolis, MN"
    assert job.description is not None and "Python and Docker" in job.description
    assert job.salary_min == 93000.0
    assert job.salary_max == 109000.0
    assert job.employment_type == "full-time"
    assert job.experience_level == "new_grad"
    assert job.source == "newgrad_jobs"
    assert job.apply_url == "https://careers.usbank.com/associate-software-engineer"


async def test_search_jobs_records_source_failure_without_aborting_other_sources():
    user_id = uuid.uuid4()
    profile = _make_profile()
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_ScalarResult(profile), _ScalarResult([]), _ScalarResult(None)]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()
    source_stats: list[dict] = []

    with (
        patch("app.services.job_service.jsearch_client.search_jobs", new_callable=AsyncMock, side_effect=RuntimeError("jsearch down")),
        patch(
            "app.services.job_service.newgrad_jobs_client.search_newgrad_jobs",
            new_callable=AsyncMock,
            return_value=[_newgrad_job(location="Toronto, ON")],
        ),
        patch("app.services.jobs.storage._find_existing_job", new_callable=AsyncMock, return_value=None),
    ):
        jobs = await search_jobs(
            db,
            user_id,
            query="software engineer",
            location="Toronto",
            sources=["jsearch", "newgrad"],
            source_stats=source_stats,
        )

    assert len(jobs) == 1
    assert {stat["source"]: stat["status"] for stat in source_stats} == {
        "jsearch": "failed",
        "newgrad": "success",
    }
    added_prefs = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and call.args[0].__class__.__name__ == "SearchPreference"
    ]
    assert added_prefs[0].location == "Toronto"


async def test_mark_stale_jobs_marks_stale_and_closed_by_last_seen_at():
    from datetime import datetime, timedelta, timezone

    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    stale_job = MagicMock()
    stale_job.last_seen_at = now - timedelta(days=20)
    stale_job.source_status = "active"
    stale_job.not_seen_count = 0
    closed_job = MagicMock()
    closed_job.last_seen_at = now - timedelta(days=60)
    closed_job.source_status = "active"
    closed_job.closed_at = None
    closed_job.not_seen_count = 2

    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult([stale_job, closed_job]))
    db.commit = AsyncMock()

    result = await mark_stale_jobs_for_user(db, user_id)

    assert result == {"stale": 1, "closed": 1}
    assert stale_job.source_status == "stale"
    assert stale_job.not_seen_count == 1
    assert closed_job.source_status == "closed"
    assert closed_job.closed_at is not None
    assert closed_job.not_seen_count == 3
    db.commit.assert_awaited_once()


async def test_store_curated_ats_payloads_filters_by_saved_search_before_store():
    from datetime import datetime, timezone

    user_id = uuid.uuid4()
    refresh_run_id = uuid.uuid4()
    profile = _make_profile()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(profile))
    db.add = MagicMock()

    pref = MagicMock()
    pref.enabled = True
    pref.mode = "default"
    pref.query = "Backend Engineer"
    pref.location = "Toronto"
    pref.remote_only = False

    stored_job = MagicMock(spec=Job)
    stored_job.source = "greenhouse"
    stored_job.ats = "greenhouse"
    stored_job.ats_slug = "shopify"

    source_payloads = {
        "greenhouse:shopify": [
            {
                "external_id": "gh_1",
                "title": "Backend Engineer",
                "company_name": "Shopify",
                "location": "Toronto, ON",
                "description": "Build services.",
                "source": "greenhouse",
                "ats": "greenhouse",
                "ats_slug": "shopify",
                "url": "https://example.com/1",
            },
            {
                "external_id": "gh_2",
                "title": "Sales Manager",
                "company_name": "Shopify",
                "location": "Vancouver, BC",
                "description": "Lead sales.",
                "source": "greenhouse",
                "ats": "greenhouse",
                "ats_slug": "shopify",
                "url": "https://example.com/2",
            },
        ]
    }
    source_stats = [{
        "source": "greenhouse:shopify",
        "status": "success",
        "started_at": datetime.now(timezone.utc),
        "finished_at": datetime.now(timezone.utc),
        "duration_seconds": 0.1,
        "raw_count": 2,
        "new_count": 0,
        "existing_count": 0,
        "duplicate_count": 0,
        "skipped_count": 0,
        "error": None,
        "details": None,
    }]

    with patch(
        "app.services.jobs.storage._store_raw_jobs",
        new_callable=AsyncMock,
        return_value=[stored_job],
    ) as store_mock:
        new_count = await store_curated_ats_payloads_for_user(
            db,
            user_id,
            source_payloads=source_payloads,
            source_stats=source_stats,
            preferences=[pref],
            refresh_run_id=refresh_run_id,
        )

    assert new_count == 1
    filtered_jobs = store_mock.await_args.args[2]
    assert [job["external_id"] for job in filtered_jobs] == ["gh_1"]
    source_run = db.add.call_args.args[0]
    assert source_run.source == "greenhouse:shopify"
    assert source_run.raw_count == 1
    assert source_run.new_count == 1


async def test_find_existing_job_prefers_source_and_external_id():
    user_id = uuid.uuid4()
    existing_job = MagicMock()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(existing_job))

    found = await _find_existing_job(
        db,
        user_id=user_id,
        source="newgrad_jobs",
        ats=None,
        external_id="newgrad_example_123",
        url="https://www.newgrad-jobs.com/list-software-engineer-jobs/example_123",
        fingerprint="fp",
    )

    assert found is existing_job
    compiled = str(db.execute.await_args.args[0])
    assert "jobs.source" in compiled
    assert "jobs.external_id" in compiled


async def test_find_existing_job_uses_no_autoflush_for_lookup_queries():
    user_id = uuid.uuid4()
    existing_job = MagicMock()

    class _NoAutoflush:
        def __init__(self):
            self.active = False

        def __enter__(self):
            self.active = True

        def __exit__(self, exc_type, exc, tb):
            self.active = False

    no_autoflush = _NoAutoflush()
    db = MagicMock()
    db.no_autoflush = no_autoflush

    async def _execute(stmt):
        assert no_autoflush.active is True
        return _ScalarResult(existing_job)

    db.execute = AsyncMock(side_effect=_execute)

    found = await _find_existing_job(
        db,
        user_id=user_id,
        source="simplify_github",
        ats=None,
        external_id="simplify_123",
        url="https://stripe.com/jobs/search?gh_jid=123",
        fingerprint="fp",
    )

    assert found is existing_job
    assert no_autoflush.active is False


async def test_find_existing_job_reuses_canonical_url_for_non_ats_sources():
    """Audit H7: URL dedup is an indexed canonical_url match (query stripped)."""
    user_id = uuid.uuid4()
    existing_job = MagicMock()
    existing_job.url = "https://www.newgrad-jobs.com/list-software-engineer-jobs/example_123"
    existing_job.canonical_url = (
        "https://www.newgrad-jobs.com/list-software-engineer-jobs/example_123"
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult([existing_job]))

    found = await _find_existing_job(
        db,
        user_id=user_id,
        source="newgrad_jobs",
        ats=None,
        external_id=None,
        url="https://www.newgrad-jobs.com/list-software-engineer-jobs/example_123?utm_source=test",
        fingerprint=None,
    )

    assert found is existing_job
    # Dedup now uses the indexed canonical_url column instead of an in-memory scan.
    compiled = str(db.execute.await_args.args[0])
    assert "jobs.canonical_url" in compiled


async def test_discover_jobs_stores_same_enriched_newgrad_fields():
    user_id = uuid.uuid4()
    profile = _make_profile()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(profile))
    db.add = MagicMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.jobs.search.search_jobs", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.services.job_service.newgrad_jobs_client.search_newgrad_jobs",
            new_callable=AsyncMock,
            return_value=[_newgrad_job()],
        ),
        patch("app.services.jobs.storage._find_existing_job", new_callable=AsyncMock, return_value=None),
        patch("app.services.jobs.curated_boards._discover_ats_boards", new_callable=AsyncMock, return_value=0),
    ):
        total_new = await discover_jobs(db, user_id)

    assert total_new == 1
    added_jobs = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and isinstance(call.args[0], Job)
    ]
    assert len(added_jobs) == 1
    job = added_jobs[0]
    assert job.location == "Minneapolis, MN"
    assert job.salary_min == 93000.0
    assert job.description is not None and "Python and Docker" in job.description
    assert job.experience_level == "new_grad"
    assert job.apply_url == "https://careers.usbank.com/associate-software-engineer"


async def test_store_raw_jobs_commits_existing_apply_url_update():
    user_id = uuid.uuid4()
    existing_job = MagicMock()
    existing_job.tags = None
    db = MagicMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.jobs.storage._load_known_startup_company_names", new_callable=AsyncMock, return_value=set()),
        patch("app.services.jobs.storage._find_existing_job", new_callable=AsyncMock, return_value=existing_job),
        patch("app.services.jobs.storage._maybe_auto_prospect", new_callable=AsyncMock) as mock_auto_prospect,
    ):
        stored = await _store_raw_jobs(db, user_id, [_newgrad_job()], _make_profile())

    assert stored == []
    assert existing_job.apply_url == "https://careers.usbank.com/associate-software-engineer"
    db.commit.assert_awaited_once()
    mock_auto_prospect.assert_not_awaited()


async def test_backfill_newgrad_jobs_updates_existing_row_in_place():
    user_id = uuid.uuid4()
    profile = _make_profile()
    job = MagicMock()
    job.id = uuid.uuid4()
    job.user_id = user_id
    job.external_id = None
    job.title = "Software Engineer"
    job.company_name = "PNC"
    job.company_logo = None
    job.location = ""
    job.remote = False
    job.url = "https://www.newgrad-jobs.com/list-software-engineer-jobs/software_engineer_at_pnc_21643566"
    job.apply_url = None
    job.description = ""
    job.employment_type = None
    job.salary_min = None
    job.salary_max = None
    job.salary_currency = None
    job.source = "newgrad_jobs"
    job.ats = None
    job.ats_slug = None
    job.posted_at = "2026-04-04T00:00:00+00:00"
    job.tags = None
    job.department = None
    job.experience_level = "mid"
    job.match_score = 5.0
    job.fingerprint = "old"

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_ScalarResult([job]), _ScalarResult(profile)])
    db.commit = AsyncMock()

    with patch(
        "app.services.newgrad_jobs_backfill_service.newgrad_jobs_client.fetch_job_detail",
        new_callable=AsyncMock,
        return_value={
            "location": "Pittsburgh, PA",
            "employment_type": "full-time",
            "work_mode": "Onsite",
            "remote": False,
            "salary_min": 90000.0,
            "salary_max": 110000.0,
            "salary_currency": "USD",
            "apply_url": "https://careers.pnc.com/software-engineer",
            "description": "<div><p>Build software systems with Python.</p></div>",
            "level_label": "Entry Level",
            "closed": False,
        },
    ):
        result = await backfill_newgrad_jobs(db, user_id=user_id)

    assert result == {"checked": 1, "updated": 1, "skipped": 0}
    assert job.external_id == "newgrad_software_engineer_at_pnc_21643566"
    assert job.apply_url == "https://careers.pnc.com/software-engineer"
    assert job.location == "Pittsburgh, PA"
    assert job.salary_min == 90000.0
    assert job.salary_max == 110000.0
    assert job.employment_type == "full-time"
    assert job.description == "<div><p>Build software systems with Python.</p></div>"
    assert job.experience_level == "new_grad"
