"""Tests for onboarding endpoint — Phase 10."""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_complete_onboarding(client, mock_user_id):
    """POST /api/settings/onboarding-complete marks onboarding done."""
    with patch(
        "app.routers.settings.settings_service.complete_onboarding",
        new_callable=AsyncMock,
    ) as mock_complete:
        resp = await client.post("/api/settings/onboarding-complete")

    assert resp.status_code == 200
    data = resp.json()
    assert data["onboarding_completed"] is True
    mock_complete.assert_called_once()


async def test_complete_onboarding_requires_auth(unauthed_client):
    """POST /api/settings/onboarding-complete returns 401 without auth."""
    resp = await unauthed_client.post("/api/settings/onboarding-complete")
    assert resp.status_code in (401, 403)


async def test_guardrails_includes_onboarding_field(client, mock_user_id):
    """GET /api/settings/guardrails includes onboarding_completed."""
    with patch(
        "app.routers.settings.settings_service.get_guardrails",
        new_callable=AsyncMock,
        return_value={
            "min_message_gap_days": 7,
            "min_message_gap_enabled": True,
            "follow_up_suggestion_enabled": True,
            "response_rate_warnings_enabled": True,
            "guardrails_acknowledged": False,
            "onboarding_completed": False,
        },
    ):
        resp = await client.get("/api/settings/guardrails")

    assert resp.status_code == 200
    data = resp.json()
    assert "onboarding_completed" in data
    assert data["onboarding_completed"] is False
