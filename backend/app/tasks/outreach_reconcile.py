"""Celery task: reconcile staged drafts (sent?) and sent outreach (replied?)."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.outreach import OutreachLog
from app.services.outreach_reconcile_service import (
    REPLY_LOOKBACK_DAYS,
    reconcile_replies,
    reconcile_sent_drafts,
)
from app.tasks import celery_app, run_async

logger = logging.getLogger(__name__)


async def _reconcile_all_users() -> dict:
    """Poll users with unreconciled staged drafts or reply-pending sent mail."""
    totals = {
        "users": 0,
        "checked": 0,
        "flipped": 0,
        "errors": 0,
        "reply_checked": 0,
        "replied": 0,
        "reply_errors": 0,
    }

    cutoff = datetime.now(timezone.utc) - timedelta(days=REPLY_LOOKBACK_DAYS)
    async with async_session() as db:
        draft_stmt = (
            select(OutreachLog.user_id)
            .where(
                OutreachLog.status == "draft",
                OutreachLog.provider.isnot(None),
                OutreachLog.provider_message_id.isnot(None),
            )
            .distinct()
        )
        reply_stmt = (
            select(OutreachLog.user_id)
            .where(
                OutreachLog.status == "sent",
                OutreachLog.response_received.is_(False),
                OutreachLog.provider.isnot(None),
                OutreachLog.provider_message_id.isnot(None),
                OutreachLog.sent_at.isnot(None),
                OutreachLog.sent_at >= cutoff,
            )
            .distinct()
        )
        draft_users = {row[0] for row in (await db.execute(draft_stmt)).all()}
        reply_users = {row[0] for row in (await db.execute(reply_stmt)).all()}

    for uid in draft_users | reply_users:
        totals["users"] += 1
        if uid in draft_users:
            try:
                async with async_session() as db:
                    stats = await reconcile_sent_drafts(db, uid)
                for key in ("checked", "flipped", "errors"):
                    totals[key] += stats.get(key, 0)
            except Exception:
                totals["errors"] += 1
                logger.exception("Outreach reconcile failed for user %s", uid)
        if uid in reply_users:
            try:
                async with async_session() as db:
                    stats = await reconcile_replies(db, uid)
                totals["reply_checked"] += stats.get("checked", 0)
                totals["replied"] += stats.get("replied", 0)
                totals["reply_errors"] += stats.get("errors", 0)
            except Exception:
                totals["reply_errors"] += 1
                logger.exception("Reply reconcile failed for user %s", uid)

    return totals


@celery_app.task(
    name="app.tasks.outreach_reconcile.reconcile_outreach_sends",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def reconcile_outreach_sends() -> dict:
    """Celery task: detect provider-side sends and thread replies."""
    return run_async(_reconcile_all_users())


async def reconcile_for_user(user_id: uuid.UUID) -> dict:
    """Public helper for on-demand reconciliation (tests / API)."""
    async with async_session() as db:
        stats = await reconcile_sent_drafts(db, user_id)
    async with async_session() as db:
        reply_stats = await reconcile_replies(db, user_id)
    stats["reply_checked"] = reply_stats.get("checked", 0)
    stats["replied"] = reply_stats.get("replied", 0)
    stats["reply_errors"] = reply_stats.get("errors", 0)
    return stats
