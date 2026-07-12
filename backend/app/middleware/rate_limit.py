"""Rate limiting configuration using slowapi.

The synchronous key callback is deliberately network-free. JWT verification
belongs in the async authentication dependency, never in this request hook.
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings

logger = logging.getLogger(__name__)


def _get_user_key(request: Request) -> str:
    """Return the peer IP for the outer, pre-authentication request budget.

    Authenticated provider/daily budgets are enforced after verification. This
    function must never parse a bearer token or trigger a JWKS request.
    """
    return get_remote_address(request)


def _build_limiter() -> Limiter:
    """Create limiter with Redis storage, falling back to in-memory if unavailable."""
    if settings.redis_url:
        try:
            import redis

            r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
            r.ping()
            return Limiter(key_func=_get_user_key, storage_uri=settings.redis_url)
        except Exception:
            if settings.environment == "production":
                raise RuntimeError("Redis is required for production rate limiting")
            logger.warning("Redis unavailable for rate limiting, using in-memory storage")
    return Limiter(key_func=_get_user_key, storage_uri="memory://")


limiter = _build_limiter()
