"""API tests for email endpoints — Phase 5."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

pytestmark = pytest.mark.asyncio


async def test_find_email(client, mock_user_id):
    """POST /api/email/find/{person_id} returns email result."""
    with patch("app.routers.email.find_email_for_person", new_callable=AsyncMock) as mock_find:
        mock_find.return_value = {
            "email": "bob@techcorp.com",
            "source": "hunter",
            "verified": True,
            "tried": ["hunter"],
        }
        person_id = str(uuid.uuid4())
        resp = await client.post(f"/api/email/find/{person_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "bob@techcorp.com"
    assert data["source"] == "hunter"
    assert data["verified"] is True


async def test_find_email_not_found(client, mock_user_id):
    """POST /api/email/find/{person_id} returns null email when exhausted."""
    with patch("app.routers.email.find_email_for_person", new_callable=AsyncMock) as mock_find:
        mock_find.return_value = {
            "email": None,
            "source": "not_found",
            "verified": False,
            "tried": ["hunter", "proxycurl", "exhausted"],
        }
        person_id = str(uuid.uuid4())
        resp = await client.post(f"/api/email/find/{person_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] is None
    assert "exhausted" in data["tried"]


async def test_find_email_person_missing(client, mock_user_id):
    """POST /api/email/find/{person_id} returns 404 for missing person."""
    with patch("app.routers.email.find_email_for_person", new_callable=AsyncMock) as mock_find:
        mock_find.side_effect = ValueError("Person not found.")
        person_id = str(uuid.uuid4())
        resp = await client.post(f"/api/email/find/{person_id}")

    assert resp.status_code == 404


async def test_email_status(client, mock_user_id):
    """GET /api/email/status returns connection status."""
    mock_settings = MagicMock()
    mock_settings.gmail_connected = True
    mock_settings.outlook_connected = False

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_settings

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    resp = await client.get("/api/email/status")

    app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["gmail_connected"] is True
    assert data["outlook_connected"] is False


async def test_gmail_auth_url(client):
    """GET /api/email/gmail/auth-url returns OAuth URL."""
    with patch("app.routers.email.gmail_service") as mock_gmail:
        mock_gmail.get_auth_url.return_value = "https://accounts.google.com/oauth?..."
        resp = await client.get(
            "/api/email/gmail/auth-url",
            params={"redirect_uri": "http://localhost:5173/callback"},
        )

    assert resp.status_code == 200
    assert "auth_url" in resp.json()


async def test_verify_email(client, mock_user_id):
    """POST /api/email/verify/{person_id} verifies email."""
    with patch("app.routers.email.verify_person_email", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = {
            "email": "bob@techcorp.com",
            "status": "valid",
            "result": "deliverable",
            "score": 95,
            "disposable": False,
            "webmail": False,
        }
        person_id = str(uuid.uuid4())
        resp = await client.post(f"/api/email/verify/{person_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "valid"
