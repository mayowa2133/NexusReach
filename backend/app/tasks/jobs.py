"""Celery tasks for automatic job feed refresh and notifications."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.tasks import celery_app
from app.database import async_session
from app.models.notification import Notification
from app.models.search_preference import SearchPreference
from app.models.company import Company
from app.services.job_service import search_jobs
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


async def _notification_exists(
    db,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    type: str,
) -> bool:
    """Check whether a notification already exists for a job + type."""
    stmt = (
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.job_id == job_id,
            Notification.type == type,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _refresh_user_feeds(user_id: uuid.UUID) -> int:
    """Re-run all enabled search preferences for a user and create notifications."""
    total_new = 0
    async with async_session() as db:
        # Fetch enabled search preferences
        stmt = select(SearchPreference).where(
            SearchPreference.user_id == user_id,
            SearchPreference.enabled == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        preferences = list(result.scalars().all())

        if not preferences:
            return 0

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

                # Record refresh metadata
                pref.last_refreshed_at = datetime.now(timezone.utc)
                pref.new_jobs_found = len(new_jobs)
                total_new += len(new_jobs)
                await db.commit()

                for job in new_jobs:
                    company_lower = job.company_name.lower().strip()

                    # Check if this job is from a starred company
                    if company_lower in starred_companies:
                        if not await _notification_exists(
                            db, user_id=user_id, job_id=job.id, type="starred_company_job",
                        ):
                            await create_notification(
                                db,
                                user_id,
                                type="starred_company_job",
                                title=f"{job.company_name} posted: {job.title}",
                                body=f"Your starred company has a new opening in {job.location or 'Unknown location'}",
                                job_id=job.id,
                            )
                    elif job.match_score is not None and job.match_score >= 50:
                        if not await _notification_exists(
                            db, user_id=user_id, job_id=job.id, type="new_job",
                        ):
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

    return total_new


async def refresh_user_feeds(user_id: uuid.UUID) -> int:
    """Public wrapper for refreshing a single user's feeds. Returns new job count."""
    count = await _refresh_user_feeds(user_id)
    return count


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


@celery_app.task(
    name="app.tasks.jobs.refresh_all_job_feeds",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def refresh_all_job_feeds() -> dict:
    """Celery task: refresh job feeds for all users with saved searches."""
    asyncio.run(_refresh_all())
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auto-discover ATS boards (Greenhouse, Ashby, Lever, Workday)
# ---------------------------------------------------------------------------

async def _discover_all_boards() -> None:
    """Run ATS board discovery for every user with at least one saved search."""
    from app.services.job_service import _discover_ats_boards  # noqa: PLC0415

    async with async_session() as db:
        stmt = (
            select(SearchPreference.user_id)
            .where(SearchPreference.enabled == True)  # noqa: E712
            .distinct()
        )
        result = await db.execute(stmt)
        user_ids = [row[0] for row in result.all()]

    logger.info("Running ATS board auto-discovery for %d users", len(user_ids))

    for uid in user_ids:
        try:
            async with async_session() as db:
                new_count = await _discover_ats_boards(db, uid)
                logger.info(
                    "ATS auto-discover: %d new jobs for user %s", new_count, uid,
                )
        except Exception:
            logger.exception("ATS auto-discover failed for user %s", uid)


@celery_app.task(
    name="app.tasks.jobs.discover_ats_boards",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def discover_ats_boards() -> dict:
    """Celery task: poll all curated ATS boards for new postings."""
    asyncio.run(_discover_all_boards())
    return {"status": "ok"}
