"""API tests for outreach endpoints — Phase 7."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


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
    log.last_contacted_at = overrides.get("last_contacted_at", datetime(2024, 3, 1, tzinfo=timezone.utc))
    log.next_follow_up_at = overrides.get("next_follow_up_at", None)
    log.response_received = overrides.get("response_received", False)
    log.created_at = datetime(2024, 3, 1, tzinfo=timezone.utc)
    log.updated_at = datetime(2024, 3, 1, tzinfo=timezone.utc)

    # Mock person relationship
    person = MagicMock()
    person.full_name = "Jane Smith"
    person.title = "Engineering Manager"
    person.company = None
    log.person = person

    # Mock job relationship
    log.job = None
    log.message = None

    return log


async def test_create_outreach(client, mock_user_id):
    """POST /api/outreach creates a new outreach log."""
    log = _mock_outreach_log(mock_user_id)

    with patch("app.routers.outreach.create_outreach_log", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = log
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


async def test_create_outreach_person_not_found(client, mock_user_id):
    """POST /api/outreach returns 400 when person not found."""
    with patch("app.routers.outreach.create_outreach_log", new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = ValueError("Person not found.")
        resp = await client.post(
            "/api/outreach",
            json={"person_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 400
    assert "Person not found" in resp.json()["detail"]


async def test_list_outreach(client, mock_user_id):
    """GET /api/outreach returns all logs."""
    log1 = _mock_outreach_log(mock_user_id, status="sent")
    log2 = _mock_outreach_log(mock_user_id, status="connected")

    with patch("app.routers.outreach.get_outreach_logs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [log1, log2]
        resp = await client.get("/api/outreach")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_list_outreach_with_status_filter(client, mock_user_id):
    """GET /api/outreach?status=sent filters by status."""
    log = _mock_outreach_log(mock_user_id, status="sent")

    with patch("app.routers.outreach.get_outreach_logs", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [log]
        resp = await client.get("/api/outreach", params={"status": "sent"})

    assert resp.status_code == 200
    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args.kwargs if mock_get.call_args.kwargs else {}
    assert call_kwargs.get("status") == "sent" or mock_get.call_args[1].get("status") == "sent"


async def test_get_single_outreach(client, mock_user_id):
    """GET /api/outreach/{id} returns a single log."""
    log = _mock_outreach_log(mock_user_id)

    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = log
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 200
    assert resp.json()["person_name"] == "Jane Smith"


async def test_get_outreach_not_found(client, mock_user_id):
    """GET /api/outreach/{id} returns 404 for missing log."""
    with patch("app.routers.outreach.get_outreach_log", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        resp = await client.get(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_update_outreach(client, mock_user_id):
    """PUT /api/outreach/{id} updates status and notes."""
    log = _mock_outreach_log(mock_user_id, status="sent", notes="Updated notes")

    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = log
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"status": "sent", "notes": "Updated notes"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


async def test_update_outreach_not_found(client, mock_user_id):
    """PUT /api/outreach/{id} returns 404 for wrong user/log."""
    with patch("app.routers.outreach.update_outreach_log", new_callable=AsyncMock) as mock_update:
        mock_update.side_effect = ValueError("Outreach log not found.")
        resp = await client.put(
            f"/api/outreach/{uuid.uuid4()}",
            json={"status": "sent"},
        )

    assert resp.status_code == 404


async def test_get_outreach_stats(client, mock_user_id):
    """GET /api/outreach/stats returns aggregate stats."""
    with patch("app.routers.outreach.get_outreach_stats", new_callable=AsyncMock) as mock_stats:
        mock_stats.return_value = {
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


async def test_get_person_timeline(client, mock_user_id):
    """GET /api/outreach/person/{id}/timeline returns chronological history."""
    log1 = _mock_outreach_log(mock_user_id, status="sent")
    log2 = _mock_outreach_log(mock_user_id, status="connected")

    with patch("app.routers.outreach.get_outreach_timeline", new_callable=AsyncMock) as mock_timeline:
        mock_timeline.return_value = [log1, log2]
        resp = await client.get(f"/api/outreach/person/{uuid.uuid4()}/timeline")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_delete_outreach(client, mock_user_id):
    """DELETE /api/outreach/{id} deletes a log."""
    with patch("app.routers.outreach.delete_outreach_log", new_callable=AsyncMock) as mock_delete:
        mock_delete.return_value = None
        resp = await client.delete(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 204


async def test_delete_outreach_not_found(client, mock_user_id):
    """DELETE /api/outreach/{id} returns 404 for missing log."""
    with patch("app.routers.outreach.delete_outreach_log", new_callable=AsyncMock) as mock_delete:
        mock_delete.side_effect = ValueError("Outreach log not found.")
        resp = await client.delete(f"/api/outreach/{uuid.uuid4()}")

    assert resp.status_code == 404
