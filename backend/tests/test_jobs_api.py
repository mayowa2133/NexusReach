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
    j.notes = overrides.get("notes", None)
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


async def test_list_jobs(client, mock_user_id):
    """GET /api/jobs returns saved jobs."""
    job1 = _mock_job(mock_user_id, match_score=80.0)
    job2 = _mock_job(mock_user_id, match_score=60.0, title="Frontend Dev")

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [job1, job2]
        resp = await client.get("/api/jobs")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_list_jobs_with_stage_filter(client, mock_user_id):
    """GET /api/jobs?stage=applied filters by stage."""
    job = _mock_job(mock_user_id, stage="applied")

    with patch("app.routers.jobs.get_jobs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [job]
        resp = await client.get("/api/jobs", params={"stage": "applied"})

    assert resp.status_code == 200
    mock_get.assert_called_once()
    # Verify the stage parameter was passed
    call_args = mock_get.call_args
    assert call_args.kwargs.get("stage") == "applied" or call_args[1].get("stage") == "applied"


async def test_get_single_job(client, mock_user_id):
    """GET /api/jobs/{id} returns a single job."""
    job = _mock_job(mock_user_id)

    with patch("app.routers.jobs.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        resp = await client.get(f"/api/jobs/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["title"] == "Software Engineer"


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
