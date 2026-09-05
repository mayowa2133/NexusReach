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
    """Verify signature and all identity-bearing Supabase JWT claims."""
    algorithm = jwt.get_unverified_header(token).get("alg")

    if not settings.supabase_url:
        raise jwt.InvalidTokenError("Supabase URL is not configured")
    decode_options = {"require": ["exp", "sub", "aud", "iss"]}
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"

    if algorithm == "ES256":
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
