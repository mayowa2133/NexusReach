"""Celery task: weekly cadence digest email."""

import asyncio
import logging

from app.database import async_session
from app.services.cadence_digest_service import send_all_cadence_digests
from app.tasks import celery_app

logger = logging.getLogger(__name__)


async def _run() -> dict:
    async with async_session() as db:
        return await send_all_cadence_digests(db)


@celery_app.task(
    name="app.tasks.cadence_digest.send_cadence_digests",
    autoretry_for=(Exception,),
    retry_backoff=120,
    retry_backoff_max=900,
    max_retries=2,
)
def send_cadence_digests() -> dict:
    """Celery task: send weekly cadence digest to all eligible users."""
    result = asyncio.run(_run())
    logger.info("Cadence digest task complete: %s", result)
    return result
