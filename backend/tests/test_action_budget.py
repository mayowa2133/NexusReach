import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.config import settings
from app.utils.action_budget import enforce_action_budget


pytestmark = pytest.mark.asyncio


async def test_action_budget_allows_up_to_limit_then_rejects():
    redis = AsyncMock()
    redis.eval = AsyncMock(side_effect=[1, 2, 3])
    with patch("app.utils.action_budget.search_cache_client._client", return_value=redis):
        user_id = uuid.uuid4()
        await enforce_action_budget(user_id, action="test", limit=2)
        await enforce_action_budget(user_id, action="test", limit=2)
        with pytest.raises(HTTPException) as exc:
            await enforce_action_budget(user_id, action="test", limit=2)
    assert exc.value.status_code == 429


async def test_action_budget_fails_closed_in_production(monkeypatch):
    redis = AsyncMock()
    redis.eval = AsyncMock(side_effect=ConnectionError("down"))
    monkeypatch.setattr(settings, "environment", "production")
    with patch("app.utils.action_budget.search_cache_client._client", return_value=redis):
        with pytest.raises(HTTPException) as exc:
            await enforce_action_budget(uuid.uuid4(), action="test", limit=2)
    assert exc.value.status_code == 503
