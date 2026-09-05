"""Retry erasure independently of removed application records."""
from app.database import async_session
from app.tasks import celery_app, run_async
from app.services.deletion_service import process_deletions


async def _run():
    async with async_session() as db:
        await process_deletions(db)


@celery_app.task(name='app.tasks.deletions.retry_pending')
def retry_pending():
    run_async(_run())
