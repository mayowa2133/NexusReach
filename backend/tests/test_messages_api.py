"""API tests for messages endpoints — Phase 4."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


def _mock_message(user_id, **overrides):
    m = MagicMock()
    m.id = overrides.get("id", uuid.uuid4())
    m.user_id = user_id
    m.person_id = overrides.get("person_id", uuid.uuid4())
    m.channel = overrides.get("channel", "email")
    m.goal = overrides.get("goal", "intro")
    m.subject = overrides.get("subject", "Intro from Alice")
    m.body = overrides.get("body", "Hi, I'd love to connect!")
    m.reasoning = overrides.get("reasoning", "Chose intro angle because...")
    m.ai_model = overrides.get("ai_model", "claude-sonnet-4-20250514")
    m.status = overrides.get("status", "draft")
    m.version = overrides.get("version", 1)
    m.parent_id = overrides.get("parent_id", None)
    m.context_snapshot = overrides.get("context_snapshot", None)
    m.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    m.updated_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    return m


def _mock_person(**overrides):
    p = MagicMock()
    company = MagicMock()
    company.id = overrides.get("company_id", uuid.uuid4())
    company.name = overrides.get("company_name", "TechCorp")
    company.domain = overrides.get("company_domain", "techcorp.com")
    company.size = overrides.get("company_size", "1000")
    company.industry = overrides.get("company_industry", "Software")
    company.description = overrides.get("company_description", None)
    company.careers_url = overrides.get("company_careers_url", None)
    p.id = overrides.get("id", uuid.uuid4())
    p.full_name = overrides.get("full_name", "Bob Jones")
    p.title = overrides.get("title", "Engineering Manager")
    p.department = overrides.get("department", None)
    p.seniority = overrides.get("seniority", None)
    p.linkedin_url = overrides.get("linkedin_url", None)
    p.github_url = overrides.get("github_url", None)
    p.work_email = overrides.get("work_email", "bob@techcorp.com")
    p.email_source = overrides.get("email_source", "pattern_suggestion")
    p.email_verified = overrides.get("email_verified", False)
    p.email_confidence = overrides.get("email_confidence", 40)
    p.email_verification_status = overrides.get("email_verification_status", "best_guess")
    p.email_verification_method = overrides.get("email_verification_method", "none")
    p.email_verification_label = overrides.get("email_verification_label", "Best guess")
    p.email_verification_evidence = overrides.get(
        "email_verification_evidence",
        "Best guess from learned company pattern.",
    )
    p.email_verified_at = overrides.get("email_verified_at", None)
    p.person_type = overrides.get("person_type", "peer")
    p.profile_data = overrides.get("profile_data", None)
    p.github_data = overrides.get("github_data", None)
    p.source = overrides.get("source", "apollo")
    p.apollo_id = overrides.get("apollo_id", None)
    p.relevance_score = overrides.get("relevance_score", None)
    p.match_quality = overrides.get("match_quality", "next_best")
    p.match_reason = overrides.get("match_reason", "Adjacent teammate.")
    p.employment_status = overrides.get("employment_status", "current")
    p.org_level = overrides.get("org_level", "ic")
    p.current_company_verified = overrides.get("current_company_verified", True)
    p.current_company_verification_status = overrides.get(
        "current_company_verification_status", "verified"
    )
    p.current_company_verification_source = overrides.get(
        "current_company_verification_source", "crawl4ai_linkedin"
    )
    p.current_company_verification_confidence = overrides.get(
        "current_company_verification_confidence", 95
    )
    p.current_company_verification_evidence = overrides.get(
        "current_company_verification_evidence", "Currently at TechCorp."
    )
    p.current_company_verified_at = overrides.get("current_company_verified_at", None)
    p.company = overrides.get("company", company)
    return p


async def test_draft_message(client, mock_user_id):
    """POST /api/messages/draft creates a draft with Claude."""
    person_id = uuid.uuid4()
    job_id = uuid.uuid4()
    msg = _mock_message(
        mock_user_id,
        goal="interview",
        person_id=person_id,
        context_snapshot={
            "recipient_strategy": "recruiter",
            "primary_cta": "interview",
            "fallback_cta": "redirect",
            "job_id": str(job_id),
        },
    )
    person = _mock_person()

    with patch("app.routers.messages.draft_message", new_callable=AsyncMock) as mock_draft:
        mock_draft.return_value = {
            "message": msg,
            "person": person,
            "reasoning": "Chose intro angle",
            "token_usage": {"input": 100, "output": 50},
            "recipient_strategy": "recruiter",
            "primary_cta": "interview",
            "fallback_cta": "redirect",
            "job_id": str(job_id),
        }
        resp = await client.post(
            "/api/messages/draft",
            json={
                "person_id": str(person_id),
                "channel": "email",
                "goal": "interview",
                "job_id": str(job_id),
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"]["channel"] == "email"
    assert data["reasoning"] == "Chose intro angle"
    assert data["message"]["recipient_strategy"] == "recruiter"
    assert data["message"]["primary_cta"] == "interview"
    assert data["message"]["fallback_cta"] == "redirect"
    assert data["message"]["job_id"] == str(job_id)
    assert data["recipient_strategy"] == "recruiter"
    assert data["job_id"] == str(job_id)
    assert mock_draft.await_args.kwargs["job_id"] == job_id


async def test_draft_message_no_profile(client, mock_user_id):
    """POST /api/messages/draft returns 400 when no profile exists."""
    with patch("app.routers.messages.draft_message", new_callable=AsyncMock) as mock_draft:
        mock_draft.side_effect = ValueError("Please complete your profile before drafting messages.")
        resp = await client.post(
            "/api/messages/draft",
            json={
                "person_id": str(uuid.uuid4()),
                "channel": "email",
                "goal": "intro",
            },
        )

    assert resp.status_code == 400
    assert "profile" in resp.json()["error"]["message"].lower()


async def test_batch_draft_messages(client, mock_user_id):
    """POST /api/messages/batch-draft returns mixed batch results."""
    person_id = uuid.uuid4()
    job_id = uuid.uuid4()
    person = _mock_person(
        id=person_id,
        full_name="Alex Lee",
        title="Software Engineer II",
        person_type="peer",
    )
    message = _mock_message(
        mock_user_id,
        person_id=person_id,
        goal="warm_intro",
        subject="Quick intro",
        body="Hi Alex",
        context_snapshot={
            "recipient_strategy": "peer",
            "primary_cta": "warm_intro",
            "fallback_cta": "redirect",
            "job_id": str(job_id),
        },
    )

    with patch("app.routers.messages.batch_draft_messages", new_callable=AsyncMock) as mock_batch:
        mock_batch.return_value = {
            "requested_count": 2,
            "ready_count": 1,
            "skipped_count": 1,
            "failed_count": 0,
            "items": [
                {
                    "status": "ready",
                    "person": person,
                    "message": message,
                    "reason": None,
                },
                {
                    "status": "skipped",
                    "person": _mock_person(full_name="Taylor Reed"),
                    "message": None,
                    "reason": "recent_outreach_within_gap",
                },
            ],
        }
        resp = await client.post(
            "/api/messages/batch-draft",
            json={
                "person_ids": [str(person_id), str(uuid.uuid4())],
                "goal": "warm_intro",
                "job_id": str(job_id),
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["requested_count"] == 2
    assert data["ready_count"] == 1
    assert data["items"][0]["status"] == "ready"
    assert data["items"][0]["message"]["recipient_strategy"] == "peer"
    assert data["items"][1]["reason"] == "recent_outreach_within_gap"
    assert mock_batch.await_args.kwargs["job_id"] == job_id


async def test_edit_message(client, mock_user_id):
    """PUT /api/messages/{id} edits a draft."""
    msg = _mock_message(mock_user_id, status="edited")

    with patch("app.routers.messages.update_message", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = msg
        resp = await client.put(
            f"/api/messages/{uuid.uuid4()}",
            json={"body": "Updated body"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "edited"


async def test_edit_message_not_found(client, mock_user_id):
    """PUT /api/messages/{id} returns 404 for wrong ID."""
    with patch("app.routers.messages.update_message", new_callable=AsyncMock) as mock_update:
        mock_update.side_effect = ValueError("Message not found.")
        resp = await client.put(
            f"/api/messages/{uuid.uuid4()}",
            json={"body": "x"},
        )

    assert resp.status_code == 404


async def test_copy_message(client, mock_user_id):
    """POST /api/messages/{id}/copy marks as copied."""
    msg = _mock_message(mock_user_id, status="copied")

    with patch("app.routers.messages.mark_copied", new_callable=AsyncMock) as mock_copy:
        mock_copy.return_value = msg
        resp = await client.post(f"/api/messages/{uuid.uuid4()}/copy")

    assert resp.status_code == 200
    assert resp.json()["status"] == "copied"


async def test_list_messages(client, mock_user_id):
    """GET /api/messages lists all messages."""
    msg = _mock_message(mock_user_id)

    with patch("app.routers.messages.get_messages", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [msg]
        resp = await client.get("/api/messages")

    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_get_single_message(client, mock_user_id):
    """GET /api/messages/{id} returns a single message."""
    msg = _mock_message(mock_user_id)

    with patch("app.routers.messages.get_message", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = msg
        resp = await client.get(f"/api/messages/{uuid.uuid4()}")

    assert resp.status_code == 200


async def test_get_message_not_found(client, mock_user_id):
    """GET /api/messages/{id} returns 404."""
    with patch("app.routers.messages.get_message", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        resp = await client.get(f"/api/messages/{uuid.uuid4()}")

    assert resp.status_code == 404
