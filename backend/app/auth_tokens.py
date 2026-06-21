"""Supabase access-token verification helpers."""

from functools import lru_cache
from typing import Any

import jwt

from app.config import settings


@lru_cache(maxsize=4)
def _get_jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(
        jwks_url,
        cache_keys=True,
        cache_jwk_set=True,
        lifespan=300,
        timeout=5,
    )


def decode_supabase_token(token: str) -> dict[str, Any]:
    """Verify a Supabase JWT using its declared, explicitly allowed algorithm."""
    algorithm = jwt.get_unverified_header(token).get("alg")

    if algorithm == "ES256":
        if not settings.supabase_url:
            raise jwt.InvalidTokenError("Supabase URL is not configured")
        signing_key = _get_jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )

    if algorithm == "HS256":
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("Supabase JWT secret is not configured")
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    raise jwt.InvalidAlgorithmError(f"Unsupported JWT algorithm: {algorithm}")
