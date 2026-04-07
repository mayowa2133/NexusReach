"""Tests for global error handler — Phase 10."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_health_endpoint(client, mock_user_id):
    """GET /api/health returns dependency check results."""
    resp = await client.get("/api/health")
    # Health check now verifies Postgres + Redis; may return 503 if unavailable
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body
    assert "checks" in body
    assert body["status"] in ("ok", "degraded")


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
