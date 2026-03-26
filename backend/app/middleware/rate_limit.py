"""Rate limiting configuration using slowapi.

Key function extracts user ID from JWT sub claim for per-user limiting,
falling back to IP address for unauthenticated endpoints.
"""

from jose import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


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


limiter = Limiter(key_func=_get_user_key, storage_uri=settings.redis_url)
