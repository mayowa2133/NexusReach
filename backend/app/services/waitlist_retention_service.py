"""Retention and erasure for pre-launch waitlist data.

Waitlist members have no account, so none of the app's normal privacy machinery
reaches them: `/api/account/delete` needs a Supabase identity they don't have.
That left the most sensitive data the product holds — an uploaded resume, plus
an IP address and free-text notes — with no expiry and no way out. This module
is both halves of the answer:

* **Retention** — a scheduled sweep drops each field once it has outlived the
  job it was collected for. `signup_ip` exists only to feed the per-IP signup
  cap, whose window is 24h, so keeping it for months is pure liability.
  Resumes are kept long enough to be useful pre-launch, then removed.
* **Erasure** — :func:`delete_signup` removes the row and the stored file
  together, so "delete my data" cannot leave an orphaned object in the bucket.

Storage failures are logged and tolerated: the DB row still goes. A stranded
object is bounded by the retention sweep, whereas refusing to delete the row
would leave the member unable to erase anything at all.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import supabase_storage_client
from app.config import settings
from app.models.waitlist import WaitlistSignup

logger = logging.getLogger(__name__)


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def purge_expired_signup_ips(db: AsyncSession) -> int:
    """Null out `signup_ip` past its retention window. Returns rows cleared.

    The live anti-fraud control is the Redis sliding window, not this column, so
    nothing depends on it after 24h — it is kept only briefly for incident
    forensics.
    """
    result = await db.execute(
        update(WaitlistSignup)
        .where(
            WaitlistSignup.signup_ip.is_not(None),
            WaitlistSignup.created_at <= _cutoff(settings.waitlist_signup_ip_retention_days),
        )
        .values(signup_ip=None)
    )
    await db.commit()
    return result.rowcount or 0


async def purge_expired_resumes(db: AsyncSession) -> int:
    """Delete stored resumes past their retention window. Returns rows cleared.

    Removes the Storage object first, then the metadata, so a failure leaves the
    row pointing at a file that still exists (retryable) rather than a row
    claiming "no resume" while the file lingers.
    """
    cutoff = _cutoff(settings.waitlist_resume_retention_days)
    result = await db.execute(
        select(WaitlistSignup).where(
            WaitlistSignup.resume_path.is_not(None),
            WaitlistSignup.resume_uploaded_at.is_not(None),
            WaitlistSignup.resume_uploaded_at <= cutoff,
        )
    )
    rows = list(result.scalars().all())
    cleared = 0
    for row in rows:
        if not await supabase_storage_client.delete_object(row.resume_path):
            logger.warning(
                "Retention: could not delete resume object for signup %s; "
                "leaving the row intact so the next sweep retries",
                row.id,
            )
            continue
        _clear_resume_fields(row)
        cleared += 1
    if cleared:
        await db.commit()
    return cleared


def _clear_resume_fields(row: WaitlistSignup) -> None:
    row.resume_path = None
    row.resume_filename = None
    row.resume_content_type = None
    row.resume_size_bytes = None
    row.resume_uploaded_at = None
    row.resume_text = None
    row.resume_parsed = None
    row.resume_parse_status = "none"


async def delete_signup(db: AsyncSession, signup: WaitlistSignup) -> dict:
    """Erase a waitlist member: their stored file and their row.

    Referrals they made are preserved as attribution: `referred_by_id` is
    ``ON DELETE SET NULL``, so an invitee's row survives with the link dropped,
    and the referrer's `verified_referral_count` is left as-is (it is a tally,
    not a pointer). Deleting someone must not silently demote other people's
    queue positions.
    """
    had_resume = bool(signup.resume_path)
    if had_resume:
        await supabase_storage_client.delete_object(signup.resume_path)

    await db.delete(signup)
    await db.commit()
    logger.info("Waitlist signup erased on request (had_resume=%s)", had_resume)
    return {"deleted": True, "resume_deleted": had_resume}
