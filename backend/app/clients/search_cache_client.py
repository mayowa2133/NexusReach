"""Redis-backed cache helpers for search-provider results."""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def _client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def get_json(key: str) -> Any | None:
    """Return cached JSON payload or ``None`` when unavailable."""
    try:
        value = await _client().get(key)
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        logger.warning("search cache read failed", extra={"cache_key": key, "error": str(exc)})
        return None

    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


async def set_json(key: str, payload: Any, *, ttl_seconds: int | None = None) -> None:
    """Store JSON payload in Redis, swallowing infra failures."""
    try:
        await _client().set(
            key,
            json.dumps(payload),
            ex=ttl_seconds or settings.search_cache_ttl_seconds,
        )
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        logger.warning("search cache write failed", extra={"cache_key": key, "error": str(exc)})
