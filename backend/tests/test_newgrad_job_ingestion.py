import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.job import Job
from app.services.job_service import _find_existing_job, discover_jobs, search_jobs
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
    db.execute = AsyncMock(side_effect=[_ScalarResult(profile), _ScalarResult(None)])
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
        patch("app.services.job_service._find_existing_job", new_callable=AsyncMock, return_value=None),
        patch(
            "app.services.auto_research_service.enqueue_auto_research_for_jobs",
            new_callable=AsyncMock,
        ),
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


async def test_find_existing_job_reuses_canonical_url_for_non_ats_sources():
    user_id = uuid.uuid4()
    existing_job = MagicMock()
    existing_job.url = "https://www.newgrad-jobs.com/list-software-engineer-jobs/example_123"
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
    compiled = str(db.execute.await_args.args[0])
    assert "jobs.source" in compiled
    assert "jobs.url IS NOT NULL" in compiled


async def test_discover_jobs_stores_same_enriched_newgrad_fields():
    user_id = uuid.uuid4()
    profile = _make_profile()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(profile))
    db.add = MagicMock()
    db.commit = AsyncMock()

    with (
        patch("app.services.job_service.search_jobs", new_callable=AsyncMock, return_value=[]),
        patch(
            "app.services.job_service.newgrad_jobs_client.search_newgrad_jobs",
            new_callable=AsyncMock,
            return_value=[_newgrad_job()],
        ),
        patch("app.services.job_service._find_existing_job", new_callable=AsyncMock, return_value=None),
        patch("app.services.job_service._discover_ats_boards", new_callable=AsyncMock, return_value=0),
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
            "description": "<div><p>Build software systems with Python.</p></div>",
            "level_label": "Entry Level",
            "closed": False,
        },
    ):
        result = await backfill_newgrad_jobs(db, user_id=user_id)

    assert result == {"checked": 1, "updated": 1, "skipped": 0}
    assert job.external_id == "newgrad_software_engineer_at_pnc_21643566"
    assert job.location == "Pittsburgh, PA"
    assert job.salary_min == 90000.0
    assert job.salary_max == 110000.0
    assert job.employment_type == "full-time"
    assert job.description == "<div><p>Build software systems with Python.</p></div>"
    assert job.experience_level == "new_grad"
