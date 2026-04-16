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
from app.services.job_service import run_startup_refresh_for_query, search_jobs
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
                pref_mode = getattr(pref, "mode", "default") or "default"
                if pref_mode == "startup":
                    new_jobs = await run_startup_refresh_for_query(
                        db=db,
                        user_id=user_id,
                        query=pref.query,
                    )
                else:
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


# --- Re-scoring ---


async def _rescore_user_jobs(user_id: uuid.UUID) -> dict:
    """Re-score all jobs for a user against their current resume/profile.

    Only re-scores jobs that haven't been scored since the profile was last
    updated, or that have never been scored.
    """
    from app.models.job import Job  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415
    from app.services.match_scoring import score_job  # noqa: PLC0415

    stats = {"rescored": 0, "skipped": 0, "errors": 0}

    async with async_session() as db:
        # Load profile
        result = await db.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile or not profile.resume_parsed:
            return stats

        profile_updated = profile.updated_at

        # Get jobs needing re-scoring: scored_at is null OR scored_at < profile.updated_at
        result = await db.execute(
            select(Job).where(
                Job.user_id == user_id,
                Job.description.isnot(None),
            )
        )
        jobs = list(result.scalars().all())

        batch_count = 0
        for job in jobs:
            # Skip if already scored after profile was last updated
            if (
                job.scored_at is not None
                and profile_updated is not None
                and job.scored_at >= profile_updated
            ):
                stats["skipped"] += 1
                continue

            try:
                job_data = {
                    "title": job.title,
                    "company_name": job.company_name,
                    "location": job.location,
                    "description": job.description,
                    "remote": job.remote,
                    "experience_level": job.experience_level,
                }
                new_score, new_breakdown = score_job(job_data, profile)
                job.match_score = new_score
                job.score_breakdown = new_breakdown
                job.scored_at = datetime.now(timezone.utc)
                stats["rescored"] += 1
                batch_count += 1

                # Flush every 50 to avoid holding too much in memory
                if batch_count >= 50:
                    await db.flush()
                    batch_count = 0
            except Exception:
                stats["errors"] += 1
                logger.debug(
                    "Re-score failed: job=%s", job.id, exc_info=True,
                )

        await db.commit()

        if stats["rescored"] > 0:
            await create_notification(
                db,
                user_id,
                type="rescore_complete",
                title="Match scores updated",
                body=f"Re-scored {stats['rescored']} jobs against your updated resume.",
            )

    return stats


@celery_app.task(
    name="app.tasks.jobs.rescore_user_jobs",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=180,
    time_limit=240,
)
def rescore_user_jobs(user_id: str) -> dict:
    """Celery task: re-score all jobs for a user after resume/profile update."""
    return asyncio.run(_rescore_user_jobs(uuid.UUID(user_id)))
