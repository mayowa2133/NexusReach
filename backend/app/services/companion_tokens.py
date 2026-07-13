"""Companion token minting and verification.

The browser companion extension holds a long-lived, revocable token instead of
the user's short-lived Supabase JWT (which expires within the hour and made
the companion silently disconnect). Token design:

- prefixed ``nrc_`` so the auth layer can route it without guessing,
- stored as a SHA-256 hash only (the plaintext is returned exactly once),
- scoped by construction: only endpoints that opt into
  ``dependencies.get_companion_or_user_id`` accept it,
- single active token per user: minting revokes all previous ones, and
  minting itself requires full Supabase auth so a stolen companion token can
  never extend or replace itself.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.companion_token import CompanionToken

COMPANION_TOKEN_PREFIX = "nrc_"

# last_used_at is a diagnostic ("is the extension still alive?"), not an audit
# log — throttle writes so every companion API call doesn't become an UPDATE.
_LAST_USED_WRITE_INTERVAL = timedelta(hours=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def mint_token(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[str, CompanionToken]:
    """Create a new companion token, revoking any previously active ones."""
    now = _now()
    await db.execute(
        update(CompanionToken)
        .where(
            CompanionToken.user_id == user_id,
            CompanionToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = COMPANION_TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = CompanionToken(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(days=settings.companion_token_ttl_days),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return token, row


async def resolve_token(db: AsyncSession, token: str) -> uuid.UUID | None:
    """Return the owning user id for a valid companion token, else ``None``."""
    if not token.startswith(COMPANION_TOKEN_PREFIX):
        return None
    result = await db.execute(
        select(CompanionToken).where(CompanionToken.token_hash == hash_token(token))
    )
    row = result.scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    now = _now()
    if row.expires_at <= now:
        return None
    if row.last_used_at is None or now - row.last_used_at >= _LAST_USED_WRITE_INTERVAL:
        row.last_used_at = now
        await db.commit()
    return row.user_id


async def revoke_tokens(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke all active tokens for the user. Returns the number revoked."""
    result = await db.execute(
        update(CompanionToken)
        .where(
            CompanionToken.user_id == user_id,
            CompanionToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    await db.commit()
    return result.rowcount or 0


async def get_status(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Server-truth companion connection status for the Settings card."""
    result = await db.execute(
        select(CompanionToken)
        .where(
            CompanionToken.user_id == user_id,
            CompanionToken.revoked_at.is_(None),
            CompanionToken.expires_at > _now(),
        )
        .order_by(CompanionToken.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {
            "connected": False,
            "created_at": None,
            "last_used_at": None,
            "expires_at": None,
        }
    return {
        "connected": True,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "expires_at": row.expires_at,
    }
