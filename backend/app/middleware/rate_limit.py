"""Rate limiting configuration using slowapi.

The synchronous key callback is deliberately network-free. JWT verification
belongs in the async authentication dependency, never in this request hook.
"""

import logging

from slowapi import Limiter
from starlette.requests import Request

from app.config import settings
from app.utils.client_ip import client_ip

logger = logging.getLogger(__name__)


def _get_user_key(request: Request) -> str:
    """Return the client IP for the outer, pre-authentication request budget.

    Resolved through ``utils.client_ip`` rather than slowapi's
    ``get_remote_address``, which reads only ``request.client.host`` — behind an
    edge proxy that is the proxy, so every caller would share one budget.

    Authenticated provider/daily budgets are enforced after verification. This
    function must never parse a bearer token or trigger a JWKS request.
    """
    return client_ip(request)


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
