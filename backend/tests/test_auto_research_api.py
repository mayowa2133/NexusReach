"""API tests for auto research endpoints."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.linkedin_graph import LinkedInGraphConnectionResponse

pytestmark = pytest.mark.asyncio


def test_linkedin_graph_connection_response_accepts_attribute_objects():
    connection = type(
        "Connection",
        (),
        {
            "id": uuid.uuid4(),
            "display_name": "Jane Doe",
            "headline": "Senior Recruiter at OpenAI",
            "current_company_name": "OpenAI",
            "linkedin_url": "https://www.linkedin.com/in/jane-doe/",
            "company_linkedin_url": "https://www.linkedin.com/company/openai/",
            "source": "csv_upload",
            "last_synced_at": None,
            "relevance_score": 88,
            "relevance_label": "high",
        },
    )()

    payload = LinkedInGraphConnectionResponse.model_validate(connection).model_dump(mode="json")

    assert payload["display_name"] == "Jane Doe"
    assert payload["relevance_score"] == 88


async def test_list_auto_research_preferences(client):
    with patch(
        "app.routers.auto_research.list_auto_research_preferences",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = []
        response = await client.get("/api/settings/auto-research")

    assert response.status_code == 200
    assert response.json() == []


async def test_upsert_auto_research_preference(client):
    preference = type(
        "Preference",
        (),
        {
            "company_name": "Stripe",
            "normalized_company_name": "stripe",
            "auto_find_people": True,
            "auto_find_emails": True,
            "created_at": datetime(2026, 4, 9),
            "updated_at": datetime(2026, 4, 9),
        },
    )()

    with patch(
        "app.routers.auto_research.upsert_auto_research_preference",
        new_callable=AsyncMock,
    ) as mock_upsert:
        mock_upsert.return_value = preference
        response = await client.put(
            "/api/settings/auto-research",
            json={
                "company_name": "Stripe",
                "auto_find_people": True,
                "auto_find_emails": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["company_name"] == "Stripe"
    assert response.json()["auto_find_emails"] is True


async def test_delete_auto_research_preference(client):
    with patch(
        "app.routers.auto_research.delete_auto_research_preference",
        new_callable=AsyncMock,
    ) as mock_delete:
        response = await client.delete(
            "/api/settings/auto-research",
            params={"company_name": "Stripe"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_delete.assert_awaited_once()


async def test_get_job_research(client):
    payload = {
        "status": "completed",
        "enabled_for_company": True,
        "auto_find_emails": True,
        "requested_at": None,
        "completed_at": None,
        "error": None,
        "company": None,
        "your_connections": [],
        "recruiters": [],
        "hiring_managers": [],
        "peers": [],
        "job_context": None,
        "errors": None,
        "email_attempted_count": 3,
        "email_found_count": 1,
    }

    with patch(
        "app.routers.jobs.get_job_research",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = payload
        response = await client.get(f"/api/jobs/{uuid.uuid4()}/research")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["email_found_count"] == 1


async def test_run_job_research(client):
    payload = {
        "status": "completed",
        "enabled_for_company": True,
        "auto_find_emails": False,
        "requested_at": None,
        "completed_at": None,
        "error": None,
        "company": None,
        "your_connections": [],
        "recruiters": [],
        "hiring_managers": [],
        "peers": [],
        "job_context": None,
        "errors": None,
        "email_attempted_count": 0,
        "email_found_count": 0,
    }

    with patch(
        "app.routers.jobs.run_job_research",
        new_callable=AsyncMock,
    ) as mock_run, patch(
        "app.routers.jobs.get_job_research",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = payload
        response = await client.post(
            f"/api/jobs/{uuid.uuid4()}/research",
            json={"target_count_per_bucket": 5},
        )

    assert response.status_code == 200
    mock_run.assert_awaited_once()
    assert mock_run.await_args.kwargs["target_count_per_bucket"] == 5
    assert response.json()["enabled_for_company"] is True
