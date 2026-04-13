"""Celery tasks for auto-prospect: background people search + email finding."""

import asyncio
import logging
import uuid

from app.tasks import celery_app
from app.database import async_session

logger = logging.getLogger(__name__)


async def _auto_prospect_job(user_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """Run people search + email finding for a single job in the background.

    1. Run search_people_for_job to find recruiters, hiring managers, peers.
    2. For each person found, attempt to find their email.
    3. Return summary stats.
    """
    from app.services.people_service import search_people_for_job  # noqa: PLC0415
    from app.services.email_finder_service import find_email_for_person  # noqa: PLC0415
    from app.services.notification_service import create_notification  # noqa: PLC0415

    stats = {
        "job_id": str(job_id),
        "people_found": 0,
        "emails_found": 0,
        "errors": 0,
    }

    async with async_session() as db:
        # Step 1: People search
        try:
            result = await search_people_for_job(
                db=db,
                user_id=user_id,
                job_id=job_id,
                target_count_per_bucket=5,
            )
        except Exception:
            logger.exception(
                "Auto-prospect people search failed: user=%s job=%s",
                user_id, job_id,
            )
            return stats

        # Collect all person IDs from the three buckets
        person_ids: list[uuid.UUID] = []
        for bucket in ("recruiters", "hiring_managers", "peers"):
            for person in result.get(bucket, []):
                pid = getattr(person, "id", None)
                if pid:
                    person_ids.append(pid)

        stats["people_found"] = len(person_ids)

        if not person_ids:
            return stats

        # Step 2: Email finding for each person
        for pid in person_ids:
            try:
                email_result = await find_email_for_person(
                    db=db,
                    user_id=user_id,
                    person_id=pid,
                    mode="best_effort",
                )
                if email_result.get("email"):
                    stats["emails_found"] += 1
            except Exception:
                stats["errors"] += 1
                logger.debug(
                    "Auto-prospect email lookup failed: person=%s", pid,
                    exc_info=True,
                )

        # Step 3: Notify user
        company_name = getattr(result.get("company"), "name", "Unknown")
        await create_notification(
            db,
            user_id,
            type="auto_prospect_complete",
            title=f"Auto-prospect: {company_name}",
            body=(
                f"Found {stats['people_found']} contacts "
                f"and {stats['emails_found']} emails."
            ),
            job_id=job_id,
        )

    return stats


@celery_app.task(
    name="app.tasks.auto_prospect.auto_prospect_job",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=300,
    time_limit=360,
)
def auto_prospect_job(user_id: str, job_id: str) -> dict:
    """Celery task: auto-prospect a single job (people search + email finding)."""
    return asyncio.run(
        _auto_prospect_job(uuid.UUID(user_id), uuid.UUID(job_id))
    )


async def _auto_draft_for_job(user_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """Draft outreach emails for all contacts found for a job.

    Only drafts for people who have an email and no existing draft for this job.
    """
    from app.models.person import Person  # noqa: PLC0415
    from app.models.message import Message  # noqa: PLC0415
    from app.services.message_service import draft_message  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    stats = {
        "job_id": str(job_id),
        "drafts_created": 0,
        "skipped": 0,
        "errors": 0,
    }

    async with async_session() as db:
        # Find all saved people for this job's company who have emails
        from app.models.job import Job  # noqa: PLC0415
        job_result = await db.execute(
            select(Job).where(Job.id == job_id, Job.user_id == user_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return stats

        # Find people at this company with emails
        result = await db.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.current_company == job.company_name,
                Person.work_email.isnot(None),
            ).limit(15)
        )
        people = list(result.scalars().all())

        for person in people:
            # Skip if draft already exists for this person + job
            existing_draft = await db.execute(
                select(Message.id).where(
                    Message.user_id == user_id,
                    Message.person_id == person.id,
                ).limit(1)
            )
            if existing_draft.scalar_one_or_none():
                stats["skipped"] += 1
                continue

            try:
                await draft_message(
                    db=db,
                    user_id=user_id,
                    person_id=person.id,
                    channel="email",
                    goal="interview" if person.person_type == "hiring_manager" else "referral",
                    job_id=job_id,
                )
                stats["drafts_created"] += 1
            except Exception:
                stats["errors"] += 1
                logger.debug(
                    "Auto-draft failed: person=%s job=%s",
                    person.id, job_id, exc_info=True,
                )

        if stats["drafts_created"] > 0:
            from app.services.notification_service import create_notification  # noqa: PLC0415
            await create_notification(
                db,
                user_id,
                type="auto_draft_complete",
                title=f"Auto-draft: {job.company_name}",
                body=f"Created {stats['drafts_created']} draft emails for {job.title}.",
                job_id=job_id,
            )

    return stats


@celery_app.task(
    name="app.tasks.auto_prospect.auto_draft_for_job",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=300,
    time_limit=360,
)
def auto_draft_for_job(user_id: str, job_id: str) -> dict:
    """Celery task: auto-draft outreach emails for a job's contacts."""
    return asyncio.run(
        _auto_draft_for_job(uuid.UUID(user_id), uuid.UUID(job_id))
    )
