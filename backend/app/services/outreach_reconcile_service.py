"""Post-send reconciliation for outreach drafts.

When the user stages a draft to Gmail/Outlook we log an OutreachLog row with
``status="draft"``. If they send from the provider UI (rather than via our
``send_staged_message`` endpoint), we never learn about it. This service
polls the provider for each outstanding draft and flips the status to
``sent`` when the message leaves the drafts folder.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach import OutreachLog
from app.services import gmail_service, outlook_service

logger = logging.getLogger(__name__)


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
