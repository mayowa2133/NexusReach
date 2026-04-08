"""Celery tasks for known people cache maintenance."""

import asyncio
import logging

from app.database import async_session
from app.services.known_people_service import mark_stale_records
from app.tasks import celery_app

logger = logging.getLogger(__name__)


async def _maintain_known_people_cache() -> dict:
    """Mark stale and expired known person records."""
    async with async_session() as db:
        result = await mark_stale_records(db, staleness_days=14, expiry_days=90)
    return result


@celery_app.task(
    name="app.tasks.known_people.maintain_known_people_cache",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def maintain_known_people_cache() -> dict:
    """Celery task: mark stale/expired records in the known people cache."""
    result = asyncio.run(_maintain_known_people_cache())
    logger.info("Known people cache maintenance: %s", result)
    return result
