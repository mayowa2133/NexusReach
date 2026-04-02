"""API tests for people endpoints — Phase 3."""

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
    p.warm_path_type = overrides.get("warm_path_type", None)
    p.warm_path_reason = overrides.get("warm_path_reason", None)
    p.warm_path_connection = overrides.get("warm_path_connection", None)
    p.company = overrides.get("company", None)
    return p


def _mock_company(user_id):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.user_id = user_id
    c.name = "TechCorp"
    c.domain = "techcorp.com"
    c.size = "500"
    c.industry = "Technology"
    c.description = "A tech company"
    c.careers_url = None
    return c


async def test_search_people(client, mock_user_id):
    """POST /api/people/search returns categorized results."""
    company = _mock_company(mock_user_id)
    recruiter = _mock_person(mock_user_id, full_name="Recruiter Bob", person_type="recruiter")
    peer = _mock_person(mock_user_id, full_name="Peer Alice", person_type="peer")

    mock_result = {
        "company": company,
        "recruiters": [recruiter],
        "hiring_managers": [],
        "peers": [peer],
    }

    with patch("app.routers.people.search_people_at_company", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_result
        resp = await client.post(
            "/api/people/search",
            json={"company_name": "TechCorp"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recruiters"]) == 1
    assert len(data["peers"]) == 1
    assert data["company"]["name"] == "TechCorp"
    assert isinstance(data["company"]["id"], str)
    assert isinstance(data["recruiters"][0]["id"], str)
    assert mock_search.await_args.kwargs["target_count_per_bucket"] == 3


async def test_search_people_passes_requested_target_count(client, mock_user_id):
    company = _mock_company(mock_user_id)
    mock_result = {
        "company": company,
        "recruiters": [],
        "hiring_managers": [],
        "peers": [],
    }

    with patch("app.routers.people.search_people_at_company", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_result
        resp = await client.post(
            "/api/people/search",
            json={"company_name": "TechCorp", "target_count_per_bucket": 7},
        )

    assert resp.status_code == 200
    assert mock_search.await_args.kwargs["target_count_per_bucket"] == 7


async def test_search_people_clamps_target_count(client, mock_user_id):
    company = _mock_company(mock_user_id)
    mock_result = {
        "company": company,
        "recruiters": [],
        "hiring_managers": [],
        "peers": [],
    }

    with patch("app.routers.people.search_people_at_company", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_result
        low_resp = await client.post(
            "/api/people/search",
            json={"company_name": "TechCorp", "target_count_per_bucket": 0},
        )
        high_resp = await client.post(
            "/api/people/search",
            json={"company_name": "TechCorp", "target_count_per_bucket": 99},
        )

    assert low_resp.status_code == 200
    assert high_resp.status_code == 200
    assert mock_search.await_args_list[0].kwargs["target_count_per_bucket"] == 1
    assert mock_search.await_args_list[1].kwargs["target_count_per_bucket"] == 10


async def test_enrich_person(client, mock_user_id):
    """POST /api/people/enrich returns enriched person."""
    person = _mock_person(mock_user_id, full_name="Enriched User")

    with patch("app.routers.people.enrich_person_from_linkedin", new_callable=AsyncMock) as mock_enrich:
        mock_enrich.return_value = person
        resp = await client.post(
            "/api/people/enrich",
            json={"linkedin_url": "https://linkedin.com/in/someone"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["full_name"] == "Enriched User"


async def test_list_people(client, mock_user_id):
    """GET /api/people returns saved people."""
    company = _mock_company(mock_user_id)
    person = _mock_person(mock_user_id, company=company)

    with patch("app.routers.people.get_saved_people", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([person], 1)
        resp = await client.get("/api/people")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["items"][0]["full_name"] == "Jane Doe"
    assert data["items"][0]["company"]["id"] == str(company.id)


async def test_verify_current_company(client, mock_user_id):
    """POST /api/people/verify-current-company returns refreshed metadata."""
    person = _mock_person(
        mock_user_id,
        current_company_verified=True,
        current_company_verification_status="verified",
        current_company_verification_source="crawl4ai_linkedin",
        current_company_verification_confidence=95,
        current_company_verification_evidence="Works at TechCorp currently.",
    )

    with patch(
        "app.routers.people.verify_current_company_for_person",
        new_callable=AsyncMock,
    ) as mock_verify:
        mock_verify.return_value = person
        resp = await client.post(f"/api/people/verify-current-company/{person.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["current_company_verified"] is True
    assert data["current_company_verification_status"] == "verified"


async def test_search_people_includes_your_connections_and_warm_path_metadata(client, mock_user_id):
    company = _mock_company(mock_user_id)
    recruiter = _mock_person(
        mock_user_id,
        full_name="Recruiter Bob",
        person_type="recruiter",
        warm_path_type="same_company_bridge",
        warm_path_reason="You already know Jane Doe at TechCorp.",
    )
    recruiter.warm_path_connection = MagicMock(
        id=uuid.uuid4(),
        display_name="Jane Doe",
        headline="Senior Recruiter",
        current_company_name="TechCorp",
        linkedin_url="https://www.linkedin.com/in/janedoe",
        company_linkedin_url="https://www.linkedin.com/company/techcorp",
        source="manual_import",
        last_synced_at=None,
    )

    mock_result = {
        "company": company,
        "your_connections": [
            {
                "id": str(uuid.uuid4()),
                "display_name": "Jane Doe",
                "headline": "Senior Recruiter",
                "current_company_name": "TechCorp",
                "linkedin_url": "https://www.linkedin.com/in/janedoe",
                "company_linkedin_url": "https://www.linkedin.com/company/techcorp",
                "source": "manual_import",
                "last_synced_at": None,
            }
        ],
        "recruiters": [recruiter],
        "hiring_managers": [],
        "peers": [],
    }

    with patch("app.routers.people.search_people_at_company", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_result
        resp = await client.post(
            "/api/people/search",
            json={"company_name": "TechCorp"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["your_connections"][0]["display_name"] == "Jane Doe"
    assert data["recruiters"][0]["warm_path_type"] == "same_company_bridge"
    assert data["recruiters"][0]["warm_path_connection"]["display_name"] == "Jane Doe"
