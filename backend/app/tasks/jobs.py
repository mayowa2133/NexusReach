"""Celery tasks for automatic job feed refresh and notifications."""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.tasks import celery_app
from app.database import async_session
from app.models.search_preference import SearchPreference
from app.models.company import Company
from app.services.job_service import search_jobs
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


async def _refresh_user_feeds(user_id: uuid.UUID) -> None:
    """Re-run all enabled search preferences for a user and create notifications."""
    async with async_session() as db:
        # Fetch enabled search preferences
        stmt = select(SearchPreference).where(
            SearchPreference.user_id == user_id,
            SearchPreference.enabled == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        preferences = list(result.scalars().all())

        if not preferences:
            return

        # Fetch starred companies for this user
        starred_stmt = select(Company).where(
            Company.user_id == user_id,
            Company.starred == True,  # noqa: E712
        )
        starred_result = await db.execute(starred_stmt)
        starred_companies = {
            c.name.lower().strip() for c in starred_result.scalars().all()
        }

        for pref in preferences:
            try:
                new_jobs = await search_jobs(
                    db=db,
                    user_id=user_id,
                    query=pref.query,
                    location=pref.location,
                    remote_only=pref.remote_only,
                )

                for job in new_jobs:
                    company_lower = job.company_name.lower().strip()

                    # Check if this job is from a starred company
                    if company_lower in starred_companies:
                        await create_notification(
                            db,
                            user_id,
                            type="starred_company_job",
                            title=f"{job.company_name} posted: {job.title}",
                            body=f"Your starred company has a new opening in {job.location or 'Unknown location'}",
                            job_id=job.id,
                        )
                    elif job.match_score is not None and job.match_score >= 50:
                        # Regular new job notification (only for good matches)
                        await create_notification(
                            db,
                            user_id,
                            type="new_job",
                            title=f"New match: {job.title} at {job.company_name}",
                            body=f"{int(job.match_score)}% match score",
                            job_id=job.id,
                        )

            except Exception:
                logger.exception(
                    "Failed to refresh feed for user %s, query '%s'",
                    user_id,
                    pref.query,
                )


async def _refresh_all() -> None:
    """Refresh job feeds for all users with enabled search preferences."""
    async with async_session() as db:
        stmt = (
            select(SearchPreference.user_id)
            .where(SearchPreference.enabled == True)  # noqa: E712
            .distinct()
        )
        result = await db.execute(stmt)
        user_ids = [row[0] for row in result.all()]

    logger.info("Refreshing job feeds for %d users", len(user_ids))

    for uid in user_ids:
        try:
            await _refresh_user_feeds(uid)
        except Exception:
            logger.exception("Failed to refresh feeds for user %s", uid)


@celery_app.task(name="app.tasks.jobs.refresh_all_job_feeds")
def refresh_all_job_feeds() -> dict:
    """Celery task: refresh job feeds for all users with saved searches."""
    asyncio.run(_refresh_all())
    return {"status": "ok"}
