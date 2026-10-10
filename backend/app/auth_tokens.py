"""Supabase access-token verification helpers."""

from functools import lru_cache
import time
from typing import Any

import jwt

from app.config import settings


class _JWKClient(jwt.PyJWKClient):
    """The library's success cooldown also needs a short outage backoff."""

    _retry_at = 0.0

    def fetch_data(self) -> Any:
        if time.monotonic() < self._retry_at:
            raise jwt.PyJWKClientConnectionError("Signing keys temporarily unavailable")
        try:
            return super().fetch_data()
        except (jwt.PyJWTError, ValueError, OSError):
            # get_signing_key serializes this boundary using the client lock.
            self._retry_at = time.monotonic() + 5
            raise jwt.PyJWKClientConnectionError("Signing keys temporarily unavailable") from None


@lru_cache(maxsize=4)
def _get_jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return _JWKClient(
        jwks_url,
        cache_keys=True,
        cache_jwk_set=True,
        lifespan=300,
        timeout=5,
        cooldown_duration=30,
    )


def decode_supabase_token(token: str) -> dict[str, Any]:
    """Verify signature and all identity-bearing Supabase JWT claims."""
    algorithm = jwt.get_unverified_header(token).get("alg")

    if not settings.supabase_url:
        raise jwt.InvalidTokenError("Supabase URL is not configured")
    decode_options = {"require": ["exp", "sub", "aud", "iss"]}
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"

    if algorithm == "ES256":
        kid = jwt.get_unverified_header(token).get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            raise jwt.InvalidTokenError("Invalid signing key identifier")
        signing_key = _get_jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=issuer,
            options=decode_options,
        )

    if algorithm == "HS256":
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("Supabase JWT secret is not configured")
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=issuer,
            options=decode_options,
        )

    raise jwt.InvalidAlgorithmError(f"Unsupported JWT algorithm: {algorithm}")
