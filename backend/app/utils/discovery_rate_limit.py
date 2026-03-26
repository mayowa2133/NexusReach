"""Per-user daily sliding-window rate limit for discovery endpoints.

Uses a Redis sorted set to track request timestamps within a 24-hour window.
This is layered on top of the existing slowapi per-minute burst limits.
"""

import logging
import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException

from app.config import settings
from app.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 86_400  # 24 hours


async def check_discovery_rate_limit(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
) -> None:
    """Enforce a sliding-window daily limit on discovery requests.

    Raises ``HTTPException(429)`` when the user has exceeded
    ``settings.discovery_daily_limit`` discovery requests in the
    past 24 hours.
    """
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = f"nexusreach:discovery_daily:{user_id}"
        now = time.time()

        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now - _WINDOW_SECONDS)
        pipe.zcard(key)
        results = await pipe.execute()
        count: int = results[1]

        if count >= settings.discovery_daily_limit:
            raise HTTPException(
                status_code=429,
                detail=f"Daily discovery limit ({settings.discovery_daily_limit}) exceeded. Try again tomorrow.",
            )

        pipe2 = r.pipeline()
        pipe2.zadd(key, {str(now): now})
        pipe2.expire(key, _WINDOW_SECONDS + 60)
        await pipe2.execute()
    except HTTPException:
        raise
    except Exception:
        # If Redis is unavailable, log and allow the request through
        # rather than blocking all discovery.
        logger.warning("Discovery rate-limit check failed; allowing request", exc_info=True)
    finally:
        await r.aclose()
