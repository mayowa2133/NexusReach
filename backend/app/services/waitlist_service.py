"""Waitlist capture service.

Public, non-user-scoped: entries come from prospective users on the landing
page. Deduped by lowercased email — a repeat submission updates the existing
row rather than erroring, so the form always succeeds for the visitor.

On join we also mint the referral primitives: a stable public ``referral_code``
and a fresh secret ``access_token`` (returned once to the browser). See
``referral_service`` for the loop mechanics.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistSignupCreate
from app.services.referral_service import (
    hash_token,
    mint_access_token,
    mint_unique_referral_code,
    resolve_referrer,
)

logger = logging.getLogger(__name__)


async def upsert_waitlist_signup(
    db: AsyncSession,
    payload: WaitlistSignupCreate,
    signup_ip: str | None = None,
) -> tuple[WaitlistSignup, bool, str]:
    """Insert a waitlist entry, or update the existing one for that email.

    Returns ``(entry, already_on_list, access_token)`` where ``access_token`` is
    the plaintext secret (stored only as a hash) the browser uses to reach the
    referral dashboard / verification link.
    """
    email = str(payload.email).strip().lower()

    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.email == email)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        # Refresh with any newly provided details, but never blank out fields
        # they gave us before with an empty resubmission.
        existing.name = payload.name or existing.name
        existing.linkedin_url = payload.linkedin_url or existing.linkedin_url
        existing.current_title = payload.current_title or existing.current_title
        existing.target_role = payload.target_role or existing.target_role
        existing.note = payload.note or existing.note
        existing.source = payload.source or existing.source
        # Rotate the secret token so a returning visitor always gets a working
        # dashboard/verify link back. The PUBLIC referral_code (already shared)
        # is intentionally left unchanged so existing ?ref= links keep working.
        raw_token = mint_access_token()
        existing.access_token_hash = hash_token(raw_token)
        await db.commit()
        await db.refresh(existing)
        logger.info("Waitlist resubmission for existing email")
        return existing, True, raw_token

    referrer = await resolve_referrer(db, payload.referred_by_code, email)
    raw_token = mint_access_token()
    entry = WaitlistSignup(
        email=email,
        name=payload.name,
        linkedin_url=payload.linkedin_url,
        current_title=payload.current_title,
        target_role=payload.target_role,
        note=payload.note,
        source=payload.source,
        referral_code=await mint_unique_referral_code(db),
        referred_by_id=referrer.id if referrer is not None else None,
        access_token_hash=hash_token(raw_token),
        signup_ip=signup_ip,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    logger.info("New waitlist signup captured (referred=%s)", referrer is not None)
    return entry, False, raw_token


async def list_waitlist_signups(db: AsyncSession) -> list[WaitlistSignup]:
    """Return all waitlist entries, newest first (admin export only)."""
    result = await db.execute(
        select(WaitlistSignup).order_by(WaitlistSignup.created_at.desc())
    )
    return list(result.scalars().all())
