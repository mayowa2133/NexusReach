"""Celery tasks for job-level auto research."""

import asyncio
import logging
import uuid

from app.database import async_session
from app.services.auto_research_service import run_job_research
from app.tasks import celery_app

logger = logging.getLogger(__name__)


async def _run_job_auto_research(user_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    async with async_session() as db:
        await run_job_research(db, user_id, job_id, force=True)
    return {"status": "ok", "job_id": str(job_id)}


@celery_app.task(
    name="app.tasks.job_research.run_job_auto_research",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def run_job_auto_research(user_id: str, job_id: str) -> dict:
    """Run job-aware people discovery and optional email lookup for one job."""
    result = asyncio.run(_run_job_auto_research(uuid.UUID(user_id), uuid.UUID(job_id)))
    logger.info("Auto research complete for job %s", job_id)
    return result
