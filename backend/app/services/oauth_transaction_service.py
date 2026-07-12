"""Short-lived, server-side OAuth transaction storage.

The authorization response must be bound to the authenticated NexusReach user
that initiated it.  A Redis-backed transaction provides a one-time state token
and PKCE verifier without exposing either relationship to the browser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.config import settings

_KEY_PREFIX = "nexusreach:oauth:transaction:"
_redis_client: aioredis.Redis | None = None


class OAuthTransactionUnavailableError(RuntimeError):
    """Raised when secure transaction storage is unavailable."""


class OAuthTransactionInvalidError(ValueError):
    """Raised for expired, replayed, or mismatched OAuth state."""


@dataclass(frozen=True)
class OAuthTransaction:
    user_id: uuid.UUID
    provider: str
    redirect_uri: str
    code_verifier: str


def _client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _state_key(state: str) -> str:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return f"{_KEY_PREFIX}{digest}"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def create_transaction(
    *, user_id: uuid.UUID, provider: str, redirect_uri: str
) -> tuple[str, str]:
    """Create a one-time state transaction and return ``(state, challenge)``."""
    try:
        for _ in range(3):
            state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(64)
            payload = json.dumps(
                {
                    "user_id": str(user_id),
                    "provider": provider,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
                separators=(",", ":"),
            )
            created = await _client().set(
                _state_key(state),
                payload,
                ex=settings.oauth_transaction_ttl_seconds,
                nx=True,
            )
            if created:
                return state, _pkce_challenge(verifier)
    except Exception as exc:
        raise OAuthTransactionUnavailableError(
            "OAuth connection is temporarily unavailable. Please try again."
        ) from exc
    raise OAuthTransactionUnavailableError(
        "OAuth connection is temporarily unavailable. Please try again."
    )


async def consume_transaction(
    *, state: str, user_id: uuid.UUID
) -> OAuthTransaction:
    """Verify the user binding, then consume the transaction exactly once."""
    if not state or len(state) > 512:
        raise OAuthTransactionInvalidError("Invalid or expired OAuth state.")
    try:
        redis = _client()
        key = _state_key(state)
        raw = await redis.get(key)
    except Exception as exc:
        raise OAuthTransactionUnavailableError(
            "OAuth connection is temporarily unavailable. Please try again."
        ) from exc
    if not raw:
        raise OAuthTransactionInvalidError("Invalid, expired, or already used OAuth state.")
    try:
        data = json.loads(raw)
        transaction = OAuthTransaction(
            user_id=uuid.UUID(str(data["user_id"])),
            provider=str(data["provider"]),
            redirect_uri=str(data["redirect_uri"]),
            code_verifier=str(data["code_verifier"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OAuthTransactionInvalidError("Invalid OAuth transaction.") from exc
    if transaction.user_id != user_id:
        raise OAuthTransactionInvalidError("OAuth state does not match this connection request.")
    try:
        consumed = await redis.getdel(key)
    except Exception as exc:
        raise OAuthTransactionUnavailableError(
            "OAuth connection is temporarily unavailable. Please try again."
        ) from exc
    if consumed != raw:
        raise OAuthTransactionInvalidError("Invalid, expired, or already used OAuth state.")
    return transaction
