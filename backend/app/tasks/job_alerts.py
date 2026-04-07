"""Celery tasks for job alert email digests."""

import asyncio
import logging

from sqlalchemy import select

from app.database import async_session
from app.models.job_alert import JobAlertPreference
from app.services.job_alert_service import send_digest_for_user
from app.tasks import celery_app

logger = logging.getLogger(__name__)


async def _send_all_digests() -> dict:
    """Send pending digests for all users with enabled job alerts."""
    async with async_session() as db:
        stmt = select(JobAlertPreference.user_id).where(
            JobAlertPreference.enabled == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        user_ids = [row[0] for row in result.all()]

    logger.info("Job alert digest: checking %d users with enabled alerts", len(user_ids))

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            async with async_session() as db:
                result = await send_digest_for_user(db, uid)
                if result["sent"]:
                    sent += 1
                elif result.get("error") and result["error"] not in (
                    "alerts_disabled", None
                ):
                    failed += 1
        except Exception:
            logger.exception("Job alert digest failed for user %s", uid)
            failed += 1

    return {"users_checked": len(user_ids), "digests_sent": sent, "failures": failed}


@celery_app.task(
    name="app.tasks.job_alerts.send_job_alert_digests",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def send_job_alert_digests() -> dict:
    """Celery task: send pending job alert digests for all enabled users."""
    result = asyncio.run(_send_all_digests())
    logger.info("Job alert digest task complete: %s", result)
    return result
