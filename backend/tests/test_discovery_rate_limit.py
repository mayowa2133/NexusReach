"""Atomic Redis sliding-window enforcement tests."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import app.utils.discovery_rate_limit as drl
from app.utils.discovery_rate_limit import check_discovery_rate_limit


@pytest.fixture(autouse=True)
def reset_rate_limit_redis_singleton():
    drl._redis_client = None
    yield
    drl._redis_client = None


@pytest.fixture
def mock_redis():
    client = AsyncMock()
    client.eval = AsyncMock(return_value=1)
    return client


@pytest.mark.asyncio
async def test_allows_request_under_limit(mock_redis):
    with patch("app.utils.discovery_rate_limit._client", return_value=mock_redis):
        await check_discovery_rate_limit(
            user_id="00000000-0000-0000-0000-000000000001"
        )
    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_blocks_request_at_limit(mock_redis):
    mock_redis.eval.return_value = 0
    with patch("app.utils.discovery_rate_limit._client", return_value=mock_redis):
        with pytest.raises(HTTPException) as exc_info:
            await check_discovery_rate_limit(
                user_id="00000000-0000-0000-0000-000000000001"
            )
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "86400"


@pytest.mark.asyncio
async def test_blocks_costly_discovery_when_redis_unavailable(monkeypatch, mock_redis):
    mock_redis.eval.side_effect = ConnectionError("Redis down")
    monkeypatch.setattr(drl.settings, "environment", "production")
    with patch("app.utils.discovery_rate_limit._client", return_value=mock_redis):
        with pytest.raises(HTTPException) as exc_info:
            await check_discovery_rate_limit(
                user_id="00000000-0000-0000-0000-000000000001"
            )
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_different_users_use_independent_atomic_keys(mock_redis):
    with patch("app.utils.discovery_rate_limit._client", return_value=mock_redis):
        await check_discovery_rate_limit(
            user_id="00000000-0000-0000-0000-000000000001"
        )
        await check_discovery_rate_limit(
            user_id="00000000-0000-0000-0000-000000000002"
        )

    keys = [str(call.args[2]) for call in mock_redis.eval.await_args_list]
    assert any("000000000001" in key for key in keys)
    assert any("000000000002" in key for key in keys)
