"""Post-send reconciliation for outreach drafts and replies.

When the user stages a draft to Gmail/Outlook we log an OutreachLog row with
``status="draft"``. If they send from the provider UI (rather than via our
``send_staged_message`` endpoint), we never learn about it. This service
polls the provider for each outstanding draft and flips the status to
``sent`` when the message leaves the drafts folder.

Once a message is sent, ``reconcile_replies`` keeps polling its thread (for
up to ``REPLY_LOOKBACK_DAYS``) and flips the status to ``responded`` when the
contact writes back - so reply tracking does not depend on the user manually
updating the CRM.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.outreach import OutreachLog
from app.observability import capture_event
from app.services import gmail_service, outlook_service
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)

# Stop polling threads for replies after this many days post-send.
REPLY_LOOKBACK_DAYS = 45


def _provider_checker(provider: str | None):
    """Look up the checker lazily so patches applied in tests are picked up."""
    if provider == "gmail":
        return gmail_service.check_draft_sent
    if provider == "outlook":
        return outlook_service.check_draft_sent
    return None


async def reconcile_sent_drafts(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, int]:
    """Poll the user's staged drafts and mark any that were sent.

    Returns a small stats dict: ``{"checked", "flipped", "errors"}``.
    """
    stats = {"checked": 0, "flipped": 0, "errors": 0}

    stmt = (
        select(OutreachLog)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.status == "draft",
            OutreachLog.provider.isnot(None),
            OutreachLog.provider_message_id.isnot(None),
        )
    )
    result = await db.execute(stmt)
    logs = list(result.scalars().all())

    for log in logs:
        checker = _provider_checker(log.provider)
        if checker is None:
            continue
        stats["checked"] += 1
        try:
            outcome = await checker(
                db,
                user_id,
                provider_message_id=log.provider_message_id,
            )
        except Exception:
            stats["errors"] += 1
            logger.exception(
                "Reconcile failed for outreach_log %s (provider=%s)",
                log.id,
                log.provider,
            )
            continue

        if outcome.get("sent"):
            now = datetime.now(timezone.utc)
            log.status = "sent"
            log.sent_at = now
            log.last_contacted_at = now
            stats["flipped"] += 1

    if stats["flipped"] > 0:
        await db.commit()

    return stats


def _reply_checker(provider: str | None):
    """Look up the reply checker lazily so patches applied in tests are picked up."""
    if provider == "gmail":
        return gmail_service.check_reply_received
    if provider == "outlook":
        return outlook_service.check_reply_received
    return None


async def reconcile_replies(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, int]:
    """Poll sent outreach threads and mark any that received a reply.

    Flips the log to ``responded`` / ``response_received`` (which feeds the
    dashboard reply metrics and the cadence engine), creates a notification,
    and emits an analytics event. Only messages sent within the last
    ``REPLY_LOOKBACK_DAYS`` are checked.

    Returns a small stats dict: ``{"checked", "replied", "errors"}``.
    """
    stats = {"checked": 0, "replied": 0, "errors": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(days=REPLY_LOOKBACK_DAYS)

    stmt = (
        select(OutreachLog)
        .options(selectinload(OutreachLog.person))
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.status == "sent",
            OutreachLog.response_received.is_(False),
            OutreachLog.provider.isnot(None),
            OutreachLog.provider_message_id.isnot(None),
            OutreachLog.sent_at.isnot(None),
            OutreachLog.sent_at >= cutoff,
        )
    )
    result = await db.execute(stmt)
    logs = list(result.scalars().all())

    for log in logs:
        checker = _reply_checker(log.provider)
        if checker is None:
            continue
        stats["checked"] += 1
        try:
            outcome = await checker(
                db,
                user_id,
                provider_message_id=log.provider_message_id,
                since=log.sent_at,
            )
        except Exception:
            stats["errors"] += 1
            logger.exception(
                "Reply reconcile failed for outreach_log %s (provider=%s)",
                log.id,
                log.provider,
            )
            continue

        if not outcome.get("replied"):
            continue

        log.status = "responded"
        log.response_received = True
        stats["replied"] += 1

        person_name = getattr(log.person, "full_name", None) if log.person else None
        title = (
            f"{person_name} replied to your outreach"
            if person_name
            else "A contact replied to your outreach"
        )
        try:
            await create_notification(
                db,
                user_id,
                type="outreach_reply",
                title=title,
                body="Open Outreach to keep the thread warm with a quick response.",
                job_id=log.job_id,
            )
        except Exception:
            logger.exception(
                "Failed to create reply notification for outreach_log %s", log.id
            )
        capture_event(
            str(user_id),
            "outreach_reply_received",
            properties={
                "provider": log.provider,
                "channel": log.channel,
                "reply_count": outcome.get("reply_count"),
            },
        )

    if stats["replied"] > 0:
        await db.commit()

    return stats
