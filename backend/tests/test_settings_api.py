"""API tests for settings/guardrails endpoints — Phase 9."""

import pytest
from unittest.mock import patch, AsyncMock

pytestmark = pytest.mark.asyncio


MOCK_DEFAULTS = {
    "min_message_gap_days": 7,
    "min_message_gap_enabled": True,
    "follow_up_suggestion_enabled": True,
    "response_rate_warnings_enabled": True,
    "guardrails_acknowledged": False,
    "onboarding_completed": False,
}

MOCK_MODIFIED = {
    "min_message_gap_days": 7,
    "min_message_gap_enabled": False,
    "follow_up_suggestion_enabled": True,
    "response_rate_warnings_enabled": False,
    "guardrails_acknowledged": True,
}


# ===========================================================================
# GET /api/settings/guardrails
# ===========================================================================


async def test_get_guardrails_returns_defaults(client, mock_user_id):
    """GET /api/settings/guardrails returns default guardrails for new user."""
    with patch(
        "app.routers.settings.settings_service.get_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = MOCK_DEFAULTS
        resp = await client.get("/api/settings/guardrails")

    assert resp.status_code == 200
    data = resp.json()
    assert data["min_message_gap_days"] == 7
    assert data["min_message_gap_enabled"] is True
    assert data["follow_up_suggestion_enabled"] is True
    assert data["response_rate_warnings_enabled"] is True
    assert data["guardrails_acknowledged"] is False


async def test_get_guardrails_returns_modified(client, mock_user_id):
    """GET /api/settings/guardrails reflects modified state."""
    with patch(
        "app.routers.settings.settings_service.get_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = MOCK_MODIFIED
        resp = await client.get("/api/settings/guardrails")

    assert resp.status_code == 200
    data = resp.json()
    assert data["min_message_gap_enabled"] is False
    assert data["response_rate_warnings_enabled"] is False
    assert data["guardrails_acknowledged"] is True


async def test_get_guardrails_has_all_fields(client, mock_user_id):
    """Response includes all expected guardrails fields."""
    with patch(
        "app.routers.settings.settings_service.get_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = MOCK_DEFAULTS
        resp = await client.get("/api/settings/guardrails")

    data = resp.json()
    expected_keys = {
        "min_message_gap_days",
        "min_message_gap_enabled",
        "follow_up_suggestion_enabled",
        "response_rate_warnings_enabled",
        "guardrails_acknowledged",
        "onboarding_completed",
    }
    assert set(data.keys()) == expected_keys


# ===========================================================================
# PUT /api/settings/guardrails
# ===========================================================================


async def test_update_guardrails_disable_toggle(client, mock_user_id):
    """PUT /api/settings/guardrails can disable a toggle."""
    updated = {**MOCK_DEFAULTS, "min_message_gap_enabled": False, "guardrails_acknowledged": True}
    with patch(
        "app.routers.settings.settings_service.update_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = updated
        resp = await client.put(
            "/api/settings/guardrails",
            json={"min_message_gap_enabled": False},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["min_message_gap_enabled"] is False
    assert data["guardrails_acknowledged"] is True


async def test_update_guardrails_change_gap_days(client, mock_user_id):
    """PUT /api/settings/guardrails can change gap days."""
    updated = {**MOCK_DEFAULTS, "min_message_gap_days": 14}
    with patch(
        "app.routers.settings.settings_service.update_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = updated
        resp = await client.put(
            "/api/settings/guardrails",
            json={"min_message_gap_days": 14},
        )

    assert resp.status_code == 200
    assert resp.json()["min_message_gap_days"] == 14


async def test_update_guardrails_partial_update(client, mock_user_id):
    """PUT with only one field updates just that field."""
    updated = {**MOCK_DEFAULTS, "follow_up_suggestion_enabled": False, "guardrails_acknowledged": True}
    with patch(
        "app.routers.settings.settings_service.update_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = updated
        resp = await client.put(
            "/api/settings/guardrails",
            json={"follow_up_suggestion_enabled": False},
        )

    assert resp.status_code == 200
    # Only the toggled field changed; others remain default
    data = resp.json()
    assert data["follow_up_suggestion_enabled"] is False
    assert data["min_message_gap_enabled"] is True
    assert data["response_rate_warnings_enabled"] is True


async def test_update_guardrails_reenable_clears_acknowledged(client, mock_user_id):
    """Re-enabling all guardrails clears the acknowledged flag."""
    updated = {**MOCK_DEFAULTS, "guardrails_acknowledged": False}
    with patch(
        "app.routers.settings.settings_service.update_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = updated
        resp = await client.put(
            "/api/settings/guardrails",
            json={
                "min_message_gap_enabled": True,
                "follow_up_suggestion_enabled": True,
                "response_rate_warnings_enabled": True,
            },
        )

    assert resp.status_code == 200
    assert resp.json()["guardrails_acknowledged"] is False


async def test_update_guardrails_invalid_gap_days(client, mock_user_id):
    """PUT with gap days out of range returns 422."""
    resp = await client.put(
        "/api/settings/guardrails",
        json={"min_message_gap_days": 0},
    )
    assert resp.status_code == 422

    resp = await client.put(
        "/api/settings/guardrails",
        json={"min_message_gap_days": 91},
    )
    assert resp.status_code == 422


async def test_update_guardrails_empty_body(client, mock_user_id):
    """PUT with empty body is valid (no changes)."""
    with patch(
        "app.routers.settings.settings_service.update_guardrails",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = MOCK_DEFAULTS
        resp = await client.put("/api/settings/guardrails", json={})

    assert resp.status_code == 200


# ===========================================================================
# Resume reuse settings
# ===========================================================================


async def test_get_resume_reuse_returns_confirmation_first_default(client, mock_user_id):
    """Resume reuse defaults to asking before reusing a saved artifact."""
    with patch(
        "app.routers.settings.settings_service.get_resume_reuse_settings",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = {"resume_auto_reuse_enabled": False}
        resp = await client.get("/api/settings/resume-reuse")

    assert resp.status_code == 200
    assert resp.json() == {"resume_auto_reuse_enabled": False}


async def test_update_resume_reuse_can_enable_auto_use(client, mock_user_id):
    """Users can opt into automatic reuse for high-scoring saved resumes."""
    with patch(
        "app.routers.settings.settings_service.update_resume_reuse_settings",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = {"resume_auto_reuse_enabled": True}
        resp = await client.put(
            "/api/settings/resume-reuse",
            json={"resume_auto_reuse_enabled": True},
        )

    assert resp.status_code == 200
    assert resp.json()["resume_auto_reuse_enabled"] is True
    m.assert_awaited_once()


# ===========================================================================
# Auth
# ===========================================================================


async def test_get_guardrails_requires_auth(unauthed_client):
    """GET /api/settings/guardrails returns 401 without auth."""
    resp = await unauthed_client.get("/api/settings/guardrails")
    assert resp.status_code in (401, 403)


async def test_update_guardrails_requires_auth(unauthed_client):
    """PUT /api/settings/guardrails returns 401 without auth."""
    resp = await unauthed_client.put(
        "/api/settings/guardrails",
        json={"min_message_gap_enabled": False},
    )
    assert resp.status_code in (401, 403)
