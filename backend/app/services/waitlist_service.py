"""Waitlist capture service.

Public, non-user-scoped: entries come from prospective users on the landing
page. Deduped by lowercased email — a repeat submission updates the existing
row rather than erroring, so the form always succeeds for the visitor.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistSignupCreate

logger = logging.getLogger(__name__)


async def upsert_waitlist_signup(
    db: AsyncSession, payload: WaitlistSignupCreate
) -> tuple[WaitlistSignup, bool]:
    """Insert a waitlist entry, or update the existing one for that email.

    Returns ``(entry, already_on_list)``.
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
        await db.commit()
        logger.info("Waitlist resubmission for existing email")
        return existing, True

    entry = WaitlistSignup(
        email=email,
        name=payload.name,
        linkedin_url=payload.linkedin_url,
        current_title=payload.current_title,
        target_role=payload.target_role,
        note=payload.note,
        source=payload.source,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    logger.info("New waitlist signup captured")
    return entry, False


async def list_waitlist_signups(db: AsyncSession) -> list[WaitlistSignup]:
    """Return all waitlist entries, newest first (admin export only)."""
    result = await db.execute(
        select(WaitlistSignup).order_by(WaitlistSignup.created_at.desc())
    )
    return list(result.scalars().all())
