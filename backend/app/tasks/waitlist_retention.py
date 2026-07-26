"""Daily retention sweep for pre-launch waitlist data.

Waitlist members have no account, so nothing else expires their data. This drops
each field once it has outlived its purpose — see
``services/waitlist_retention_service`` for the reasoning behind each window.

Idempotent and cheap: both queries are bounded by an indexed timestamp and do
nothing once the backlog is clear.
"""

import logging

from app.database import async_session
from app.services.waitlist_retention_service import (
    purge_expired_resumes,
    purge_expired_signup_ips,
)
from app.tasks import celery_app, run_async

logger = logging.getLogger(__name__)


async def _run() -> dict:
    async with async_session() as db:
        ips = await purge_expired_signup_ips(db)
        resumes = await purge_expired_resumes(db)
    return {"signup_ips_cleared": ips, "resumes_deleted": resumes}


@celery_app.task(
    name="app.tasks.waitlist_retention.purge_waitlist_pii",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def purge_waitlist_pii() -> dict:
    """Celery task: expire waitlist IPs and resumes past their retention window."""
    result = run_async(_run())
    logger.info("Waitlist retention sweep: %s", result)
    return result
