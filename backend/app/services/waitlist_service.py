"""Waitlist capture service.

Public, non-user-scoped: entries come from prospective users on the landing
page. Deduped by lowercased email; a repeat submission is a no-op so the form
always succeeds without exposing or modifying an existing signup.

**An existing row is read-only to this endpoint — nothing goes in, nothing
secret comes out.** It is unauthenticated and idempotent per address, so anyone
can submit anyone's email. Handing back that row's owner token (or its name and
queue position) would be a takeover; *writing* to it would let a stranger
rewrite someone's name, LinkedIn URL and note, or replace their stored resume.
Neither is distinguishable from a genuine returning visitor at this layer, so a
resubmission does nothing. Recovery is a separate, heavily throttled mailbox
flow.

Consequence worth knowing: a member who signed up and later wants to add a
resume or fix a typo cannot do it by resubmitting the form. That needs a
token-authenticated edit on the referral dashboard, which does not exist yet.

See ``referral_service`` for the loop mechanics and the two-token split.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistSignupCreate
from app.services.referral_service import (
    mint_unique_referral_code,
    resolve_referrer,
)
from app.utils.waitlist_goals import clean_goals, clean_target_occupation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WaitlistUpsertResult:
    """Outcome of a signup submission.

    ``access_token`` is populated ONLY for a brand-new row, whose data the
    submitter just supplied — there is no other owner to impersonate. For an
    existing row it is ``None`` in the response path and delivered by email
    instead (``emailed_access_token``).
    """

    entry: WaitlistSignup
    already_on_list: bool
    #: Safe to return over HTTP (new rows only).
    access_token: str | None
    #: Email-delivery only — a dashboard key for a returning, verified member.
    emailed_access_token: str | None
    #: Email-delivery only — single-use confirmation key.
    verification_token: str | None


async def upsert_waitlist_signup(
    db: AsyncSession,
    payload: WaitlistSignupCreate,
    signup_ip: str | None = None,
) -> WaitlistUpsertResult:
    """Insert a waitlist entry, or re-issue a link for an existing email.

    Despite the name this only ever *inserts*: an existing row's fields are left
    untouched (see the module docstring). Kept as ``upsert_…`` because it is
    still the single idempotent entry point for a signup submission.
    """
    email = str(payload.email).strip().lower()

    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.email == email)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        return WaitlistUpsertResult(entry=existing, already_on_list=True,
            access_token=None, emailed_access_token=None, verification_token=None)

    referrer = await resolve_referrer(db, payload.referred_by_code, email)
    entry = WaitlistSignup(
        email=email,
        name=payload.name,
        linkedin_url=payload.linkedin_url,
        current_title=payload.current_title,
        target_role=payload.target_role,
        target_occupation=clean_target_occupation(payload.target_occupation),
        note=payload.note,
        source=payload.source,
        goals=clean_goals(payload.goals),
        referral_code=await mint_unique_referral_code(db),
        referred_by_id=referrer.id if referrer is not None else None,
        signup_ip=signup_ip,
    )
    from app.services.referral_credentials import campaign, issue
    await campaign(db)
    db.add(entry)
    await db.flush()
    access_token = None
    verification_token = await issue(db, entry, 'exchange')
    await db.commit()
    await db.refresh(entry)
    logger.info("New waitlist signup captured (referred=%s)", referrer is not None)
    return WaitlistUpsertResult(
        entry=entry,
        already_on_list=False,
        access_token=access_token,
        emailed_access_token=None,
        verification_token=verification_token,
    )


async def list_waitlist_signups(db: AsyncSession) -> list[WaitlistSignup]:
    """Return all waitlist entries, newest first (admin export only)."""
    result = await db.execute(
        select(WaitlistSignup).order_by(WaitlistSignup.created_at.desc())
    )
    return list(result.scalars().all())
