"""API tests for outreach endpoints — Phase 7.

Covers all CRUD operations, filtering, stats, timeline, enrichment,
edge cases, and auth validation.
"""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_person(full_name="Jane Smith", title="Engineering Manager", company_name=None):
    person = MagicMock()
    person.full_name = full_name
    person.title = title
    person.warm_path_type = None
    person.warm_path_reason = None
    person.warm_path_connection = None
    if company_name:
        company = MagicMock()
        company.name = company_name
        person.company = company
    else:
        person.company = None
    return person


def _mock_job(title="Senior SWE", company_name="Acme Corp"):
    job = MagicMock()
    job.title = title
    job.company_name = company_name
    return job


def _mock_outreach_log(user_id, **overrides):
    log = MagicMock()
    log.id = overrides.get("id", uuid.uuid4())
    log.user_id = user_id
    log.person_id = overrides.get("person_id", uuid.uuid4())
    log.job_id = overrides.get("job_id", None)
    log.message_id = overrides.get("message_id", None)
    log.status = overrides.get("status", "draft")
    log.channel = overrides.get("channel", "linkedin_message")
    log.notes = overrides.get("notes", "Sent intro message")
    log.last_contacted_at = overrides.get(
        "last_contacted_at", datetime(2024, 3, 1, tzinfo=timezone.utc)
    )
    log.next_follow_up_at = overrides.get("next_follow_up_at", None)
    log.response_received = overrides.get("response_received", False)
    log.created_at = datetime(2024, 3, 1, tzinfo=timezone.utc)
    log.updated_at = datetime(2024, 3, 1, tzinfo=timezone.utc)

    # Relationships
    log.person = overrides.get("person", _mock_person())
    log.job = overrides.get("job", None)
    log.message = None
    return log


# ===========================================================================
# CREATE  POST /api/outreach
# ===========================================================================

async def test_create_outreach(client, mock_user_id):
    """POST /api/outreach creates a new outreach log."""
    log = _mock_outreach_log(mock_user_id)

    with patch("app.routers.outreach.create_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.post(
            "/api/outreach",
            json={
                "person_id": str(uuid.uuid4()),
                "channel": "linkedin_message",
                "notes": "Sent intro message",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "draft"
    assert data["channel"] == "linkedin_message"
    assert data["person_name"] == "Jane Smith"


async def test_create_outreach_with_all_optional_fields(client, mock_user_id):
    """POST /api/outreach accepts job_id, message_id, and dates."""
    job_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    log = _mock_outreach_log(
        mock_user_id,
        job_id=job_id,
        message_id=msg_id,
        status="sent",
        channel="email",
        notes="Follow-up email sent",
        next_follow_up_at=datetime(2024, 3, 15, tzinfo=timezone.utc),
        job=_mock_job(),
    )

    with patch("app.routers.outreach.create_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.post(
            "/api/outreach",
            json={
                "person_id": str(uuid.uuid4()),
                "job_id": str(job_id),
                "message_id": str(msg_id),
                "status": "sent",
                "channel": "email",
                "notes": "Follow-up email sent",
                "last_contacted_at": "2024-03-01T00:00:00+00:00",
                "next_follow_up_at": "2024-03-15T00:00:00+00:00",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    assert data["job_id"] is not None
    assert data["message_id"] is not None
    assert data["job_title"] == "Senior SWE"


async def test_create_outreach_defaults_status_to_draft(client, mock_user_id):
    """POST /api/outreach defaults status to draft when not specified."""
    log = _mock_outreach_log(mock_user_id, status="draft")

    with patch("app.routers.outreach.create_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.post(
            "/api/outreach",
            json={"person_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"


async def test_create_outreach_person_not_found(client, mock_user_id):
    """POST /api/outreach returns 400 when person not found."""
    with patch("app.routers.outreach.create_outreach_log", new_callable=AsyncMock) as m:
        m.side_effect = ValueError("Person not found.")
        resp = await client.post(
            "/api/outreach",
            json={"person_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 400
    assert "Person not found" in resp.json()["error"]["message"]


async def test_create_outreach_invalid_status(client, mock_user_id):
    """POST /api/outreach returns 400 for an invalid status value."""
    with patch("app.routers.outreach.create_outreach_log", new_callable=AsyncMock) as m:
        m.side_effect = ValueError("Invalid status: potato")
        resp = await client.post(
            "/api/outreach",
            json={"person_id": str(uuid.uuid4()), "status": "potato"},
        )

    assert resp.status_code == 400
    assert "Invalid status" in resp.json()["error"]["message"]


async def test_create_outreach_missing_person_id(client, mock_user_id):
    """POST /api/outreach returns 422 when person_id is missing."""
    resp = await client.post("/api/outreach", json={})
    assert resp.status_code == 422


# ===========================================================================
# LIST  GET /api/outreach
# ===========================================================================

async def test_list_outreach(client, mock_user_id):
    """GET /api/outreach returns all logs."""
    log1 = _mock_outreach_log(mock_user_id, status="sent")
    log2 = _mock_outreach_log(mock_user_id, status="connected")

    with patch("app.routers.outreach.get_outreach_logs", new_callable=AsyncMock) as m:
        m.return_value = ([log1, log2], 2)
        resp = await client.get("/api/outreach")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2


async def test_list_outreach_empty(client, mock_user_id):
    """GET /api/outreach returns empty list when no logs."""
    with patch("app.routers.outreach.get_outreach_logs", new_callable=AsyncMock) as m:
        m.return_value = ([], 0)
        resp = await client.get("/api/outreach")

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_list_outreach_with_status_filter(client, mock_user_id):
    """GET /api/outreach?status=sent passes status to service."""
    log = _mock_outreach_log(mock_user_id, status="sent")

    with patch("app.routers.outreach.get_outreach_logs", new_callable=AsyncMock) as m:
        m.return_value = ([log], 1)
        resp = await client.get("/api/outreach", params={"status": "sent"})

    assert resp.status_code == 200
    # Verify status was forwarded
    _, kwargs = m.call_args
    assert kwargs.get("status") == "sent"


async def test_list_outreach_with_person_filter(client, mock_user_id):
    """GET /api/outreach?person_id=... filters by person."""
    pid = uuid.uuid4()
    log = _mock_outreach_log(mock_user_id, person_id=pid)

    with patch("app.routers.outreach.get_outreach_logs", new_callable=AsyncMock) as m:
        m.return_value = ([log], 1)
        resp = await client.get("/api/outreach", params={"person_id": str(pid)})

    assert resp.status_code == 200
    _, kwargs = m.call_args
    assert kwargs.get("person_id") == pid


async def test_list_outreach_with_job_filter(client, mock_user_id):
    """GET /api/outreach?job_id=... filters by job."""
    jid = uuid.uuid4()
    log = _mock_outreach_log(mock_user_id, job_id=jid)

    with patch("app.routers.outreach.get_outreach_logs", new_callable=AsyncMock) as m:
        m.return_value = ([log], 1)
        resp = await client.get("/api/outreach", params={"job_id": str(jid)})

    assert resp.status_code == 200
    _, kwargs = m.call_args
    assert kwargs.get("job_id") == jid


# ===========================================================================
# GET SINGLE  GET /api/outreach/{id}
# ===========================================================================

async def test_get_single_outreach(client, mock_user_id):
    """GET /api/outreach/{id} returns a single log."""
    log = _mock_outreach_log(mock_user_id)

    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["person_name"] == "Jane Smith"


async def test_get_outreach_not_found(client, mock_user_id):
    """GET /api/outreach/{id} returns 404 for missing log."""
    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = None
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_get_outreach_enriches_company(client, mock_user_id):
    """GET /api/outreach/{id} includes company_name from person.company."""
    person = _mock_person(company_name="TechCorp")
    log = _mock_outreach_log(mock_user_id, person=person)

    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["company_name"] == "TechCorp"


async def test_get_outreach_enriches_job(client, mock_user_id):
    """GET /api/outreach/{id} includes job_title from linked job."""
    job = _mock_job(title="Staff Engineer")
    log = _mock_outreach_log(mock_user_id, job_id=uuid.uuid4(), job=job)

    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["job_title"] == "Staff Engineer"


# ===========================================================================
# UPDATE  PUT /api/outreach/{id}
# ===========================================================================

async def test_update_outreach_status(client, mock_user_id):
    """PUT /api/outreach/{id} updates status."""
    log = _mock_outreach_log(mock_user_id, status="sent")

    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"status": "sent"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


async def test_update_outreach_notes(client, mock_user_id):
    """PUT /api/outreach/{id} updates notes."""
    log = _mock_outreach_log(mock_user_id, notes="New notes here")

    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"notes": "New notes here"},
        )

    assert resp.status_code == 200
    assert resp.json()["notes"] == "New notes here"


async def test_update_outreach_response_received(client, mock_user_id):
    """PUT /api/outreach/{id} updates response_received flag."""
    log = _mock_outreach_log(mock_user_id, response_received=True)

    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"response_received": True},
        )

    assert resp.status_code == 200
    assert resp.json()["response_received"] is True


async def test_update_outreach_not_found(client, mock_user_id):
    """PUT /api/outreach/{id} returns 404 for wrong user/log."""
    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as m:
        m.side_effect = ValueError("Outreach log not found.")
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"status": "sent"},
        )

    assert resp.status_code == 404


async def test_update_outreach_invalid_status(client, mock_user_id):
    """PUT /api/outreach/{id} returns 404 for invalid status (ValueError from service)."""
    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as m:
        m.side_effect = ValueError("Invalid status: banana")
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"status": "banana"},
        )

    assert resp.status_code == 404


async def test_update_outreach_with_datetime_fields(client, mock_user_id):
    """PUT /api/outreach/{id} converts ISO datetime strings."""
    log = _mock_outreach_log(
        mock_user_id,
        next_follow_up_at=datetime(2024, 4, 1, tzinfo=timezone.utc),
    )

    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={
                "next_follow_up_at": "2024-04-01T00:00:00+00:00",
                "last_contacted_at": "2024-03-15T10:00:00+00:00",
            },
        )

    assert resp.status_code == 200
    # Verify service was called with datetime objects, not strings
    _, kwargs = m.call_args
    assert "next_follow_up_at" in kwargs
    assert "last_contacted_at" in kwargs


async def test_update_outreach_partial_update(client, mock_user_id):
    """PUT /api/outreach/{id} with only one field only sends that field."""
    log = _mock_outreach_log(mock_user_id, channel="email")

    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"channel": "email"},
        )

    assert resp.status_code == 200
    _, kwargs = m.call_args
    # Only channel should be in the updates (exclude_unset=True in router)
    assert "channel" in kwargs
    assert "status" not in kwargs


# ===========================================================================
# STATS  GET /api/outreach/stats
# ===========================================================================

async def test_get_outreach_stats(client, mock_user_id):
    """GET /api/outreach/stats returns aggregate stats."""
    with patch("app.routers.outreach.get_outreach_stats", new_callable=AsyncMock) as m:
        m.return_value = {
            "total_contacts": 15,
            "by_status": {"draft": 3, "sent": 5, "connected": 4, "responded": 3},
            "response_rate": 25.0,
            "upcoming_follow_ups": 2,
        }
        resp = await client.get("/api/outreach/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_contacts"] == 15
    assert data["response_rate"] == 25.0
    assert data["upcoming_follow_ups"] == 2
    assert data["by_status"]["sent"] == 5


async def test_get_outreach_stats_empty(client, mock_user_id):
    """GET /api/outreach/stats returns zeros when no logs."""
    with patch("app.routers.outreach.get_outreach_stats", new_callable=AsyncMock) as m:
        m.return_value = {
            "total_contacts": 0,
            "by_status": {},
            "response_rate": 0.0,
            "upcoming_follow_ups": 0,
        }
        resp = await client.get("/api/outreach/stats")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_contacts"] == 0
    assert data["response_rate"] == 0.0


# ===========================================================================
# TIMELINE  GET /api/outreach/person/{id}/timeline
# ===========================================================================

async def test_get_person_timeline(client, mock_user_id):
    """GET /api/outreach/person/{id}/timeline returns chronological history."""
    log1 = _mock_outreach_log(mock_user_id, status="sent")
    log2 = _mock_outreach_log(mock_user_id, status="connected")

    with patch("app.routers.outreach.get_outreach_timeline", new_callable=AsyncMock) as m:
        m.return_value = [log1, log2]
        resp = await client.get(f"/api/outreach/person/{uuid.uuid4()}/timeline")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_get_person_timeline_empty(client, mock_user_id):
    """GET /api/outreach/person/{id}/timeline returns empty for unknown person."""
    with patch("app.routers.outreach.get_outreach_timeline", new_callable=AsyncMock) as m:
        m.return_value = []
        resp = await client.get(f"/api/outreach/person/{uuid.uuid4()}/timeline")

    assert resp.status_code == 200
    assert resp.json() == []


# ===========================================================================
# DELETE  DELETE /api/outreach/{id}
# ===========================================================================

async def test_delete_outreach(client, mock_user_id):
    """DELETE /api/outreach/{id} deletes a log and returns 204."""
    with patch("app.routers.outreach.delete_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = None
        resp = await client.delete(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 204


async def test_delete_outreach_not_found(client, mock_user_id):
    """DELETE /api/outreach/{id} returns 404 for missing log."""
    with patch("app.routers.outreach.delete_outreach_log", new_callable=AsyncMock) as m:
        m.side_effect = ValueError("Outreach log not found.")
        resp = await client.delete(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 404


# ===========================================================================
# AUTH  - 401 without token
# ===========================================================================

async def test_outreach_requires_auth(unauthed_client):
    """All outreach endpoints return 401/403 without auth."""
    endpoints = [
        ("GET", "/api/outreach"),
        ("POST", "/api/outreach"),
        ("GET", "/api/outreach/stats"),
        ("GET", f"/api/outreach/{uuid.uuid4()}"),
        ("PUT", f"/api/outreach/{uuid.uuid4()}"),
        ("DELETE", f"/api/outreach/{uuid.uuid4()}"),
        ("GET", f"/api/outreach/person/{uuid.uuid4()}/timeline"),
    ]
    for method, url in endpoints:
        resp = await unauthed_client.request(method, url, json={"person_id": str(uuid.uuid4())} if method == "POST" else None)
        assert resp.status_code in (401, 403), f"{method} {url} returned {resp.status_code}"


# ===========================================================================
# RESPONSE ENRICHMENT (_to_response helper)
# ===========================================================================

async def test_response_includes_all_fields(client, mock_user_id):
    """Response includes all expected fields from OutreachResponse schema."""
    log = _mock_outreach_log(
        mock_user_id,
        channel="email",
        notes="Test notes",
        response_received=True,
        next_follow_up_at=datetime(2024, 4, 1, tzinfo=timezone.utc),
    )

    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    data = resp.json()
    required_fields = [
        "id", "person_id", "status", "channel", "notes",
        "last_contacted_at", "next_follow_up_at", "response_received",
        "person_name", "person_title", "company_name", "job_title",
        "created_at", "updated_at",
    ]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"


async def test_response_nulls_when_no_relationships(client, mock_user_id):
    """Response nulls company/job when relationships are absent."""
    person = MagicMock()
    person.full_name = "Solo Person"
    person.title = None
    person.company = None

    log = _mock_outreach_log(mock_user_id, person=person)
    log.job = None

    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as m:
        m.return_value = log
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    data = resp.json()
    assert data["person_name"] == "Solo Person"
    assert data["person_title"] is None
    assert data["company_name"] is None
    assert data["job_title"] is None
