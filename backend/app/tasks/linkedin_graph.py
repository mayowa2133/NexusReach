"""Celery task: clean up orphaned LinkedIn graph sync sessions."""

import asyncio
import logging

from app.database import async_session
from app.services.linkedin_graph_service import cleanup_orphaned_sync_sessions
from app.tasks import celery_app

logger = logging.getLogger(__name__)


async def _cleanup_orphaned_sessions() -> dict:
    async with async_session() as db:
        return await cleanup_orphaned_sync_sessions(db)


@celery_app.task(
    name="app.tasks.linkedin_graph.cleanup_orphaned_sync_sessions",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def cleanup_orphaned_sync_sessions_task() -> dict:
    """Periodic task to clean up orphaned LinkedIn graph sync sessions."""
    result = asyncio.get_event_loop().run_until_complete(_cleanup_orphaned_sessions())
    logger.info("LinkedIn graph orphaned session cleanup: %s", result)
    return result
