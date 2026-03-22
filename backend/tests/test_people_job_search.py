"""API tests for job-aware people search — Phase 11."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

pytestmark = pytest.mark.asyncio


def _mock_person(user_id, **overrides):
    p = MagicMock()
    p.id = overrides.get("id", uuid.uuid4())
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
    p.email_confidence = overrides.get("email_confidence", None)
    p.email_verification_status = overrides.get("email_verification_status", None)
    p.email_verification_method = overrides.get("email_verification_method", None)
    p.email_verification_label = overrides.get("email_verification_label", None)
    p.email_verification_evidence = overrides.get("email_verification_evidence", None)
    p.email_verified_at = overrides.get("email_verified_at", None)
    p.person_type = overrides.get("person_type", "peer")
    p.profile_data = overrides.get("profile_data", {})
    p.github_data = overrides.get("github_data", None)
    p.source = overrides.get("source", "apollo")
    p.apollo_id = overrides.get("apollo_id", None)
    p.match_quality = overrides.get("match_quality", None)
    p.match_reason = overrides.get("match_reason", None)
    p.company_match_confidence = overrides.get("company_match_confidence", None)
    p.fallback_reason = overrides.get("fallback_reason", None)
    p.employment_status = overrides.get("employment_status", None)
    p.org_level = overrides.get("org_level", None)
    p.current_company_verified = overrides.get("current_company_verified", None)
    p.current_company_verification_status = overrides.get("current_company_verification_status", None)
    p.current_company_verification_source = overrides.get("current_company_verification_source", None)
    p.current_company_verification_confidence = overrides.get("current_company_verification_confidence", None)
    p.current_company_verification_evidence = overrides.get("current_company_verification_evidence", None)
    p.current_company_verified_at = overrides.get("current_company_verified_at", None)
    p.company = overrides.get("company", None)
    return p


def _mock_company(user_id):
    c = MagicMock()
    c.id = uuid.uuid4()
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
    assert data["company"]["id"] == str(company.id)
    assert isinstance(data["peers"][0]["id"], str)
    assert mock_search.await_args.kwargs["target_count_per_bucket"] == 3


async def test_search_with_job_id_passes_requested_target_count(client, mock_user_id):
    company = _mock_company(mock_user_id)
    mock_result = {
        "company": company,
        "recruiters": [],
        "hiring_managers": [],
        "peers": [],
        "job_context": {
            "department": "engineering",
            "team_keywords": [],
            "seniority": "junior",
        },
    }

    with patch("app.routers.people.search_people_for_job", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_result
        resp = await client.post(
            "/api/people/search",
            json={
                "company_name": "Stripe",
                "job_id": str(uuid.uuid4()),
                "target_count_per_bucket": 6,
            },
        )

    assert resp.status_code == 200
    assert mock_search.await_args.kwargs["target_count_per_bucket"] == 6


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
