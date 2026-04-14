"""Celery tasks for auto-prospect: background people search + email finding + auto-send."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

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
    If auto_stage_on_apply is enabled, stages drafts to the connected inbox.
    If auto_send_enabled is also on, schedules sends after the configured delay.
    """
    from app.models.person import Person  # noqa: PLC0415
    from app.models.message import Message  # noqa: PLC0415
    from app.services.message_service import draft_message  # noqa: PLC0415
    from app.services.settings_service import get_auto_prospect  # noqa: PLC0415
    from app.services.draft_staging_service import (  # noqa: PLC0415
        stage_message_draft,
        resolve_connected_provider,
    )

    from sqlalchemy import select  # noqa: PLC0415

    stats = {
        "job_id": str(job_id),
        "drafts_created": 0,
        "staged_count": 0,
        "scheduled_send_count": 0,
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

        # Load settings for auto-stage / auto-send
        ap_settings = await get_auto_prospect(db, user_id)
        auto_stage = ap_settings.get("auto_stage_on_apply", False)
        auto_send = ap_settings.get("auto_send_enabled", False)
        send_delay = ap_settings.get("auto_send_delay_minutes", 30)

        # Resolve email provider once if staging is needed
        provider = None
        if auto_stage:
            provider = await resolve_connected_provider(db, user_id)

        # Find people at this company with emails
        result = await db.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.current_company == job.company_name,
                Person.work_email.isnot(None),
            ).limit(15)
        )
        people = list(result.scalars().all())

        drafted_message_ids: list[uuid.UUID] = []

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
                draft_result = await draft_message(
                    db=db,
                    user_id=user_id,
                    person_id=person.id,
                    channel="email",
                    goal="interview" if person.person_type == "hiring_manager" else "referral",
                    job_id=job_id,
                )
                stats["drafts_created"] += 1
                msg = draft_result.get("message") if isinstance(draft_result, dict) else None
                if msg:
                    msg_id = getattr(msg, "id", None) or (msg.get("id") if isinstance(msg, dict) else None)
                    if msg_id:
                        drafted_message_ids.append(
                            msg_id if isinstance(msg_id, uuid.UUID) else uuid.UUID(str(msg_id))
                        )
            except Exception:
                stats["errors"] += 1
                logger.debug(
                    "Auto-draft failed: person=%s job=%s",
                    person.id, job_id, exc_info=True,
                )

        # Auto-stage drafted messages if provider is available
        if auto_stage and provider and drafted_message_ids:
            for msg_id in drafted_message_ids:
                try:
                    await stage_message_draft(
                        db=db,
                        user_id=user_id,
                        message_id=msg_id,
                        provider=provider,
                    )
                    stats["staged_count"] += 1

                    # Schedule auto-send if enabled
                    if auto_send:
                        msg_result = await db.execute(
                            select(Message).where(Message.id == msg_id)
                        )
                        msg_obj = msg_result.scalar_one_or_none()
                        if msg_obj:
                            msg_obj.scheduled_send_at = datetime.now(timezone.utc) + timedelta(
                                minutes=send_delay
                            )
                            await db.commit()
                            stats["scheduled_send_count"] += 1
                except Exception:
                    logger.debug(
                        "Auto-stage failed: message=%s", msg_id, exc_info=True,
                    )

        if stats["drafts_created"] > 0:
            from app.services.notification_service import create_notification  # noqa: PLC0415
            body_parts = [f"Created {stats['drafts_created']} draft emails for {job.title}."]
            if stats["staged_count"]:
                body_parts.append(f"Staged {stats['staged_count']} to inbox.")
            if stats["scheduled_send_count"]:
                body_parts.append(f"Scheduled {stats['scheduled_send_count']} to send in {send_delay}min.")
            await create_notification(
                db,
                user_id,
                type="auto_draft_complete",
                title=f"Auto-draft: {job.company_name}",
                body=" ".join(body_parts),
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


async def _process_pending_sends() -> dict:
    """Send messages whose scheduled_send_at has passed.

    Re-checks auto_send_enabled at send time. If disabled, clears all
    scheduled_send_at timestamps for that user (cancels queue).
    Rate-limited to 10 sends per user per cycle.
    """
    from sqlalchemy import select, distinct  # noqa: PLC0415
    from app.models.message import Message  # noqa: PLC0415
    from app.models.settings import UserSettings  # noqa: PLC0415
    from app.services.draft_staging_service import (  # noqa: PLC0415
        send_staged_message,
        resolve_connected_provider,
    )
    from app.services.notification_service import create_notification  # noqa: PLC0415

    stats = {"sent": 0, "cancelled": 0, "errors": 0}
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # Find all users with pending sends
        user_ids_result = await db.execute(
            select(distinct(Message.user_id)).where(
                Message.status == "staged",
                Message.scheduled_send_at.isnot(None),
                Message.scheduled_send_at <= now,
            )
        )
        user_ids = [row[0] for row in user_ids_result.all()]

        for uid in user_ids:
            # Re-check setting
            settings_result = await db.execute(
                select(UserSettings).where(UserSettings.user_id == uid)
            )
            user_settings = settings_result.scalar_one_or_none()

            if not user_settings or not user_settings.auto_send_enabled:
                # Cancel all scheduled sends for this user
                pending_result = await db.execute(
                    select(Message).where(
                        Message.user_id == uid,
                        Message.scheduled_send_at.isnot(None),
                    )
                )
                for msg in pending_result.scalars().all():
                    msg.scheduled_send_at = None
                    stats["cancelled"] += 1
                await db.commit()
                continue

            # Get up to 10 ready messages
            ready_result = await db.execute(
                select(Message).where(
                    Message.user_id == uid,
                    Message.status == "staged",
                    Message.scheduled_send_at.isnot(None),
                    Message.scheduled_send_at <= now,
                ).limit(10)
            )
            ready_messages = list(ready_result.scalars().all())

            provider = await resolve_connected_provider(db, uid)
            if not provider:
                # No provider — cancel and notify
                for msg in ready_messages:
                    msg.scheduled_send_at = None
                    stats["cancelled"] += 1
                await db.commit()
                await create_notification(
                    db, uid,
                    type="auto_send_failed",
                    title="Auto-send cancelled",
                    body="No email provider connected. Scheduled sends cancelled.",
                )
                continue

            sent_count = 0
            for msg in ready_messages:
                try:
                    await send_staged_message(
                        db=db,
                        user_id=uid,
                        message_id=msg.id,
                        provider=provider,
                    )
                    stats["sent"] += 1
                    sent_count += 1
                except Exception:
                    stats["errors"] += 1
                    msg.scheduled_send_at = None
                    await db.commit()
                    logger.debug(
                        "Auto-send failed: message=%s", msg.id, exc_info=True,
                    )

            if sent_count > 0:
                await create_notification(
                    db, uid,
                    type="auto_send_complete",
                    title="Auto-send complete",
                    body=f"Sent {sent_count} email(s) automatically.",
                )

    return stats


@celery_app.task(
    name="app.tasks.auto_prospect.process_pending_sends",
    soft_time_limit=120,
    time_limit=180,
)
def process_pending_sends() -> dict:
    """Celery beat task: process scheduled auto-sends every 5 minutes."""
    return asyncio.run(_process_pending_sends())
