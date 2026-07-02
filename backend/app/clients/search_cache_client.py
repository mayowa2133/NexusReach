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


async def ping() -> bool:
    """Return True if Redis responds to PING."""
    try:
        return bool(await _client().ping())
    except Exception:
        return False


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


async def acquire_debounce(key: str, *, ttl_seconds: int) -> bool:
    """Best-effort distributed debounce via SET NX EX.

    Returns True when the caller acquired the slot (key was absent and is now
    held for ``ttl_seconds``), False when the slot is already held OR Redis is
    unavailable. Fail-closed on error is deliberate: a Redis outage must not let
    a per-visit nudge fan out into a discovery storm — the background beat keeps
    feeds fresh regardless.
    """
    try:
        return bool(await _client().set(key, "1", ex=ttl_seconds, nx=True))
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        logger.warning("debounce acquire failed", extra={"cache_key": key, "error": str(exc)})
        return False


async def acquire_lock(key: str, *, ttl_seconds: int) -> bool:
    """Best-effort distributed mutex via SET NX EX.

    Unlike ``acquire_debounce`` this fails OPEN: on a Redis outage it returns
    True so the guarded work still runs (a lock outage must not stop feed
    refreshes — worst case we lose mutual exclusion, which is the pre-lock
    status quo). The TTL is a crash backstop; release with ``release_lock``.
    """
    try:
        return bool(await _client().set(key, "1", ex=ttl_seconds, nx=True))
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        logger.warning("lock acquire failed", extra={"cache_key": key, "error": str(exc)})
        return True


async def release_lock(key: str) -> None:
    """Release a lock taken with ``acquire_lock``; swallows infra failures."""
    try:
        await _client().delete(key)
    except Exception as exc:  # pragma: no cover - network failures are environment-specific
        logger.warning("lock release failed", extra={"cache_key": key, "error": str(exc)})


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
