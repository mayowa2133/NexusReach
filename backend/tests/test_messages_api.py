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
    m.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    m.updated_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    return m


def _mock_person(**overrides):
    p = MagicMock()
    p.full_name = overrides.get("full_name", "Bob Jones")
    p.title = overrides.get("title", "Engineering Manager")
    return p


async def test_draft_message(client, mock_user_id):
    """POST /api/messages/draft creates a draft with Claude."""
    msg = _mock_message(mock_user_id)
    person = _mock_person()

    with patch("app.routers.messages.draft_message", new_callable=AsyncMock) as mock_draft:
        mock_draft.return_value = {
            "message": msg,
            "person": person,
            "reasoning": "Chose intro angle",
            "token_usage": {"input": 100, "output": 50},
        }
        resp = await client.post(
            "/api/messages/draft",
            json={
                "person_id": str(uuid.uuid4()),
                "channel": "email",
                "goal": "intro",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message"]["channel"] == "email"
    assert data["reasoning"] == "Chose intro angle"


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
