"""API tests for job-aware people search — Phase 11."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

pytestmark = pytest.mark.asyncio


def _mock_person(user_id, **overrides):
    p = MagicMock()
    p.id = str(uuid.uuid4())
    p.user_id = user_id
    p.company_id = None
    p.full_name = overrides.get("full_name", "Jane Doe")
    p.title = overrides.get("title", "Software Engineer")
    p.department = overrides.get("department", "Engineering")
    p.seniority = overrides.get("seniority", "mid")
    p.linkedin_url = overrides.get("linkedin_url", "https://linkedin.com/in/janedoe")
    p.github_url = overrides.get("github_url", None)
    p.work_email = overrides.get("work_email", None)
    p.email_source = None
    p.email_verified = False
    p.person_type = overrides.get("person_type", "peer")
    p.profile_data = overrides.get("profile_data", {})
    p.github_data = overrides.get("github_data", None)
    p.source = overrides.get("source", "apollo")
    p.apollo_id = overrides.get("apollo_id", None)
    p.company = overrides.get("company", None)
    return p


def _mock_company(user_id):
    c = MagicMock()
    c.id = str(uuid.uuid4())
    c.user_id = user_id
    c.name = "Stripe"
    c.domain = "stripe.com"
    c.size = "5000"
    c.industry = "Financial Services"
    c.description = "Online payments"
    c.careers_url = None
    return c


async def test_search_with_job_id(client, mock_user_id):
    """POST /api/people/search with job_id returns job_context in response."""
    company = _mock_company(mock_user_id)
    peer = _mock_person(mock_user_id, full_name="Backend Dev", person_type="peer")

    mock_result = {
        "company": company,
        "recruiters": [],
        "hiring_managers": [],
        "peers": [peer],
        "job_context": {
            "department": "engineering",
            "team_keywords": ["backend"],
            "seniority": "senior",
        },
    }

    with patch("app.routers.people.search_people_for_job", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_result
        resp = await client.post(
            "/api/people/search",
            json={
                "company_name": "Stripe",
                "job_id": str(uuid.uuid4()),
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_context"] is not None
    assert data["job_context"]["department"] == "engineering"
    assert "backend" in data["job_context"]["team_keywords"]


async def test_search_without_job_id_still_works(client, mock_user_id):
    """POST /api/people/search without job_id uses generic search (backward compat)."""
    company = _mock_company(mock_user_id)
    recruiter = _mock_person(mock_user_id, full_name="Recruiter", person_type="recruiter")

    mock_result = {
        "company": company,
        "recruiters": [recruiter],
        "hiring_managers": [],
        "peers": [],
    }

    with patch("app.routers.people.search_people_at_company", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_result
        resp = await client.post(
            "/api/people/search",
            json={"company_name": "Stripe"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_context"] is None
    assert len(data["recruiters"]) == 1


async def test_search_invalid_job_id(client, mock_user_id):
    """POST /api/people/search with invalid job_id returns 400."""
    resp = await client.post(
        "/api/people/search",
        json={
            "company_name": "Stripe",
            "job_id": "not-a-uuid",
        },
    )
    assert resp.status_code == 400


async def test_search_nonexistent_job_id(client, mock_user_id):
    """POST /api/people/search with non-existent job_id returns 404."""
    with patch("app.routers.people.search_people_for_job", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = ValueError("Job not found")
        resp = await client.post(
            "/api/people/search",
            json={
                "company_name": "Stripe",
                "job_id": str(uuid.uuid4()),
            },
        )

    assert resp.status_code == 404
