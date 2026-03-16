"""API tests for auth endpoints — Phase 1."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


pytestmark = pytest.mark.asyncio


async def test_get_me_returns_user(client, mock_user_id):
    """GET /api/auth/me returns user info when authenticated."""
    mock_user = MagicMock()
    mock_user.id = mock_user_id
    mock_user.email = "test@example.com"
    mock_user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

    with patch("app.routers.auth.get_or_create_user"):
        from app.dependencies import get_or_create_user
        from app.main import app

        app.dependency_overrides[get_or_create_user] = lambda: mock_user

        resp = await client.get("/api/auth/me")

        app.dependency_overrides.pop(get_or_create_user, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(mock_user_id)
    assert data["email"] == "test@example.com"


async def test_get_me_unauthorized(unauthed_client):
    """GET /api/auth/me returns 401/403 without token."""
    resp = await unauthed_client.get("/api/auth/me")
    assert resp.status_code in (401, 403)
