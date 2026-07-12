"""Redis-backed per-user budgets for externally costly actions."""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

from app.clients import search_cache_client
from app.config import settings

logger = logging.getLogger(__name__)

_INCREMENT_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


async def enforce_action_budget(
    user_id: uuid.UUID,
    *,
    action: str,
    limit: int,
    window_seconds: int = 86_400,
) -> None:
    """Consume one action slot or reject safely when the budget is exhausted."""
    if limit <= 0:
        raise HTTPException(status_code=503, detail="This action is currently disabled.")
    key = f"nexusreach:action_budget:{action}:{user_id}"
    try:
        count = int(
            await search_cache_client._client().eval(
                _INCREMENT_WITH_TTL, 1, key, window_seconds
            )
        )
    except Exception:
        logger.error("Action budget backend unavailable", extra={"action": action}, exc_info=True)
        if settings.environment == "production":
            raise HTTPException(
                status_code=503,
                detail="This action is temporarily unavailable. Please try again shortly.",
            )
        return
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily {action.replace('_', ' ')} limit ({limit}) exceeded.",
        )
