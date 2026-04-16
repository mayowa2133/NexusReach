"""Celery task: reconcile staged email drafts against provider send state."""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.database import async_session
from app.models.outreach import OutreachLog
from app.services.outreach_reconcile_service import reconcile_sent_drafts
from app.tasks import celery_app

logger = logging.getLogger(__name__)


async def _reconcile_all_users() -> dict:
    """Poll every user who has at least one unreconciled staged draft."""
    totals = {"users": 0, "checked": 0, "flipped": 0, "errors": 0}

    async with async_session() as db:
        stmt = (
            select(OutreachLog.user_id)
            .where(
                OutreachLog.status == "draft",
                OutreachLog.provider.isnot(None),
                OutreachLog.provider_message_id.isnot(None),
            )
            .distinct()
        )
        result = await db.execute(stmt)
        user_ids = [row[0] for row in result.all()]

    for uid in user_ids:
        totals["users"] += 1
        try:
            async with async_session() as db:
                stats = await reconcile_sent_drafts(db, uid)
            for key in ("checked", "flipped", "errors"):
                totals[key] += stats.get(key, 0)
        except Exception:
            totals["errors"] += 1
            logger.exception("Outreach reconcile failed for user %s", uid)

    return totals


@celery_app.task(
    name="app.tasks.outreach_reconcile.reconcile_outreach_sends",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def reconcile_outreach_sends() -> dict:
    """Celery task: detect drafts sent from Gmail/Outlook UI."""
    return asyncio.run(_reconcile_all_users())


async def reconcile_for_user(user_id: uuid.UUID) -> dict:
    """Public helper for on-demand reconciliation (tests / API)."""
    async with async_session() as db:
        return await reconcile_sent_drafts(db, user_id)
