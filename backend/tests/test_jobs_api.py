"""API tests for jobs endpoints — Phase 6."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


def _mock_job(user_id, **overrides):
    j = MagicMock()
    j.id = overrides.get("id", uuid.uuid4())
    j.user_id = user_id
    j.title = overrides.get("title", "Software Engineer")
    j.company_name = overrides.get("company_name", "TechCorp")
    j.company_logo = overrides.get("company_logo", None)
    j.location = overrides.get("location", "New York, NY")
    j.remote = overrides.get("remote", False)
    j.url = overrides.get("url", "https://example.com/job/1")
    j.description = overrides.get("description", "Build things")
    j.employment_type = overrides.get("employment_type", "full_time")
    j.salary_min = overrides.get("salary_min", 100000.0)
    j.salary_max = overrides.get("salary_max", 150000.0)
    j.salary_currency = overrides.get("salary_currency", "USD")
    j.source = overrides.get("source", "jsearch")
    j.ats = overrides.get("ats", None)
    j.posted_at = overrides.get("posted_at", "2024-01-15")
    j.match_score = overrides.get("match_score", 75.0)
    j.score_breakdown = overrides.get("score_breakdown", {"role_match": 30, "skills_match": 20})
    j.stage = overrides.get("stage", "discovered")
    j.tags = overrides.get("tags", None)
    j.department = overrides.get("department", None)
    j.experience_level = overrides.get("experience_level", None)
    j.notes = overrides.get("notes", None)
    j.starred = overrides.get("starred", False)
    j.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    j.updated_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    return j


async def test_search_jobs(client, mock_user_id):
    """POST /api/jobs/search returns scored job results."""
    job = _mock_job(mock_user_id)

    with patch("app.routers.jobs.search_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search",
            json={"query": "software engineer", "remote_only": False},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Software Engineer"
    assert data[0]["match_score"] == 75.0


async def test_search_ats(client, mock_user_id):
    """POST /api/jobs/search/ats returns ATS board results."""
    job = _mock_job(mock_user_id, source="greenhouse", ats="greenhouse")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={"company_slug": "stripe", "ats_type": "greenhouse"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source"] == "greenhouse"


async def test_search_ats_with_job_url(client, mock_user_id):
    """POST /api/jobs/search/ats accepts a direct job posting URL."""
    job = _mock_job(mock_user_id, source="greenhouse", ats="greenhouse")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={"job_url": "https://job-boards.greenhouse.io/affirm/jobs/7550577003"},
        )

    assert resp.status_code == 200
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["job_url"] == "https://job-boards.greenhouse.io/affirm/jobs/7550577003"
    assert call_kwargs["company_slug"] is None
    assert call_kwargs["ats_type"] is None


async def test_search_ats_with_apple_job_url(client, mock_user_id):
    """POST /api/jobs/search/ats accepts Apple Jobs exact-job URLs."""
    job = _mock_job(mock_user_id, source="apple_jobs", ats="apple_jobs", company_name="Apple")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={
                "job_url": (
                    "https://jobs.apple.com/en-us/details/200652765/software-engineer-core-os-telemetry"
                    "?board_id=17682&jr_id=69bdc46c393a1008f7434e68"
                )
            },
        )

    assert resp.status_code == 200
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["job_url"].startswith("https://jobs.apple.com/en-us/details/200652765/")


async def test_search_ats_with_workday_job_url(client, mock_user_id):
    """POST /api/jobs/search/ats accepts Workday exact-job URLs."""
    job = _mock_job(mock_user_id, source="workday", ats="workday", company_name="NVIDIA")

    with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = [job]
        resp = await client.post(
            "/api/jobs/search/ats",
            json={
                "job_url": (
                    "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
                    "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
                    "?jr_id=69bd8442b106024562826cc8"
                )
            },
        )

    assert resp.status_code == 200
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args.kwargs
    assert call_kwargs["job_url"].startswith("https://nvidia.wd5.myworkdayjobs.com/")


async def test_search_ats_accepts_dev_mode_without_token(unauthed_client, monkeypatch):
    """POST /api/jobs/search/ats works without Authorization in dev auth mode."""
    from app.database import get_db
    from app.main import app
    from app.config import settings

    fake_db = MagicMock()

    async def _override_db():
        yield fake_db

    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "dev_user_id", uuid.UUID("00000000-0000-0000-0000-000000000001"))
    monkeypatch.setattr(settings, "dev_user_email", "dev@nexusreach.local")
    app.dependency_overrides[get_db] = _override_db

    job = _mock_job(settings.dev_user_id, source="lever", ats="lever")

    try:
        with patch("app.routers.jobs.search_ats_jobs", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = [job]
            resp = await unauthed_client.post(
                "/api/jobs/search/ats",
                json={"job_url": "https://jobs.lever.co/pointclickcare/471f17d7-98b4-446c-9f62-796aa783a648"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()[0]["ats"] == "lever"


async def test_list_jobs(client, mock_user_id):
    """GET /api/jobs returns saved jobs."""
    job1 = _mock_job(mock_user_id, match_score=80.0)
    job2 = _mock_job(mock_user_id, match_score=60.0, title="Frontend Dev")

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([job1, job2], 2)
        resp = await client.get("/api/jobs")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2


async def test_list_jobs_with_stage_filter(client, mock_user_id):
    """GET /api/jobs?stage=applied filters by stage."""
    job = _mock_job(mock_user_id, stage="applied")

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([job], 1)
        resp = await client.get("/api/jobs", params={"stage": "applied"})

    assert resp.status_code == 200
    mock_get.assert_called_once()
    # Verify the stage parameter was passed
    call_args = mock_get.call_args
    assert call_args.kwargs.get("stage") == "applied" or call_args[1].get("stage") == "applied"


async def test_list_jobs_with_startup_filter(client, mock_user_id):
    """GET /api/jobs?startup=true filters startup-tagged jobs."""
    job = _mock_job(mock_user_id, tags=["startup", "startup_source:yc_jobs"])

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([job], 1)
        resp = await client.get("/api/jobs", params={"startup": "true"})

    assert resp.status_code == 200
    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert call_args.kwargs.get("startup") is True or call_args[1].get("startup") is True


async def test_get_single_job(client, mock_user_id):
    """GET /api/jobs/{id} returns a single job."""
    job = _mock_job(mock_user_id)

    with patch("app.routers.jobs.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        resp = await client.get(f"/api/jobs/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["title"] == "Software Engineer"


async def test_discover_jobs_startup_mode(client):
    """POST /api/jobs/discover forwards startup mode to the service."""
    with patch("app.routers.jobs.discover_jobs", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = 4
        resp = await client.post("/api/jobs/discover", json={"mode": "startup"})

    assert resp.status_code == 200
    assert resp.json() == {"new_jobs_found": 4}
    mock_discover.assert_awaited_once()
    call_kwargs = mock_discover.call_args.kwargs
    assert call_kwargs["mode"] == "startup"


async def test_get_job_not_found(client, mock_user_id):
    """GET /api/jobs/{id} returns 404 for missing job."""
    with patch("app.routers.jobs.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        resp = await client.get(f"/api/jobs/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_update_job_stage(client, mock_user_id):
    """PUT /api/jobs/{id}/stage updates kanban stage."""
    job = _mock_job(mock_user_id, stage="applied")

    with patch("app.routers.jobs.update_job_stage", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = job
        resp = await client.put(
            f"/api/jobs/{uuid.uuid4()}/stage",
            json={"stage": "applied"},
        )

    assert resp.status_code == 200
    assert resp.json()["stage"] == "applied"


async def test_update_job_stage_not_found(client, mock_user_id):
    """PUT /api/jobs/{id}/stage returns 404 for wrong user/job."""
    with patch("app.routers.jobs.update_job_stage", new_callable=AsyncMock) as mock_update:
        mock_update.side_effect = ValueError("Job not found.")
        resp = await client.put(
            f"/api/jobs/{uuid.uuid4()}/stage",
            json={"stage": "applied"},
        )

    assert resp.status_code == 404
