"""Celery task: clean up orphaned LinkedIn graph sync sessions."""

import logging

from sqlalchemy.exc import ProgrammingError

from app.database import async_session
from app.services.linkedin_graph_service import cleanup_orphaned_sync_sessions
from app.tasks import celery_app, run_async

logger = logging.getLogger(__name__)


def _is_missing_linkedin_graph_sync_runs_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return 'relation "linkedin_graph_sync_runs" does not exist' in message


async def _cleanup_orphaned_sessions() -> dict:
    async with async_session() as db:
        try:
            return await cleanup_orphaned_sync_sessions(db)
        except ProgrammingError as exc:
            if not _is_missing_linkedin_graph_sync_runs_table_error(exc):
                raise
            await db.rollback()
            logger.warning(
                "Skipping cleanup_orphaned_sync_sessions because the linkedin_graph_sync_runs table is unavailable. "
                "Database migrations may not be applied yet."
            )
            return {"cleaned_up": 0}


@celery_app.task(
    name="app.tasks.linkedin_graph.cleanup_orphaned_sync_sessions",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def cleanup_orphaned_sync_sessions_task() -> dict:
    """Periodic task to clean up orphaned LinkedIn graph sync sessions."""
    result = run_async(_cleanup_orphaned_sessions())
    logger.info("LinkedIn graph orphaned session cleanup: %s", result)
    return result
