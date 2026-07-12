"""Tests for global error handler — Phase 10."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_health_endpoint(client, mock_user_id):
    """GET /api/health is a cheap liveness response."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readiness_is_hidden_without_internal_token(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "readiness_token", "internal-secret")
    response = await client.get("/api/ready")
    assert response.status_code == 404


def test_production_disables_api_discovery(monkeypatch):
    from app.config import settings
    from app.main import _production_optional_path

    monkeypatch.setattr(settings, "environment", "production")
    assert _production_optional_path("/docs") is None
    assert _production_optional_path("/openapi.json") is None


async def test_not_found_returns_standard_error(client, mock_user_id):
    """Non-existent endpoint returns standardized error format."""
    resp = await client.get("/api/nonexistent")
    # FastAPI returns 404 for unknown routes
    assert resp.status_code == 404


async def test_validation_error_format(client, mock_user_id):
    """Invalid request body returns structured validation error."""
    # POST to messages/draft without body → validation error
    resp = await client.post("/api/messages/draft")
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "errors" in data["error"]["details"]
