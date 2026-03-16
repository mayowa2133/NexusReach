"""Tests for API usage tracking endpoints — Phase 10."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


# --- Helpers ---

def _mock_daily_usage():
    return {
        "total_calls": 5,
        "total_tokens_in": 2500,
        "total_tokens_out": 1200,
        "total_cost_cents": 0,
        "daily_call_limit": 50,
        "daily_token_limit": 100000,
        "calls_remaining": 45,
        "tokens_remaining": 96300,
    }


# --- Tests ---


async def test_get_daily_usage(client, mock_user_id):
    """GET /api/usage/daily returns usage summary."""
    with patch(
        "app.routers.usage.api_usage_service.get_daily_usage",
        new_callable=AsyncMock,
        return_value=_mock_daily_usage(),
    ):
        resp = await client.get("/api/usage/daily")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 5
    assert data["calls_remaining"] == 45
    assert data["daily_call_limit"] == 50
    assert data["daily_token_limit"] == 100000


async def test_get_daily_usage_zero(client, mock_user_id):
    """GET /api/usage/daily returns zeros when no usage today."""
    with patch(
        "app.routers.usage.api_usage_service.get_daily_usage",
        new_callable=AsyncMock,
        return_value={
            "total_calls": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_cost_cents": 0,
            "daily_call_limit": 50,
            "daily_token_limit": 100000,
            "calls_remaining": 50,
            "tokens_remaining": 100000,
        },
    ):
        resp = await client.get("/api/usage/daily")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 0
    assert data["calls_remaining"] == 50


async def test_get_daily_usage_requires_auth(unauthed_client):
    """GET /api/usage/daily returns 401 without auth."""
    resp = await unauthed_client.get("/api/usage/daily")
    assert resp.status_code in (401, 403)


async def test_usage_response_has_all_fields(client, mock_user_id):
    """Response includes all expected fields."""
    with patch(
        "app.routers.usage.api_usage_service.get_daily_usage",
        new_callable=AsyncMock,
        return_value=_mock_daily_usage(),
    ):
        resp = await client.get("/api/usage/daily")

    data = resp.json()
    expected_fields = {
        "total_calls",
        "total_tokens_in",
        "total_tokens_out",
        "total_cost_cents",
        "daily_call_limit",
        "daily_token_limit",
        "calls_remaining",
        "tokens_remaining",
    }
    assert set(data.keys()) == expected_fields
