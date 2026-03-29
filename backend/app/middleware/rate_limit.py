"""Rate limiting configuration using slowapi.

Key function extracts user ID from JWT sub claim for per-user limiting,
falling back to IP address for unauthenticated endpoints.
"""

import logging

from jose import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings

logger = logging.getLogger(__name__)


def _get_user_key(request: Request) -> str:
    """Extract rate-limit key: JWT sub claim if present, else remote IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(auth[7:], options={"verify_signature": False})
            sub = payload.get("sub")
            if sub:
                return str(sub)
        except Exception:
            pass
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
            logger.warning("Redis unavailable for rate limiting, using in-memory storage")
    return Limiter(key_func=_get_user_key, storage_uri="memory://")


limiter = _build_limiter()
