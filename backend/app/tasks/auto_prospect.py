"""Celery tasks for auto-prospect: background people search + email finding + auto-send."""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.tasks import celery_app, run_async
from app.database import async_session

logger = logging.getLogger(__name__)


def _is_missing_messages_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return 'relation "messages" does not exist' in message


async def _auto_prospect_job(user_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """Run people search + email finding for a single job in the background.

    1. Run search_people_for_job to find recruiters, hiring managers, peers.
    2. For each person found, attempt to find their email.
    3. Return summary stats.
    """
    from app.services.people import search_people_for_job  # noqa: PLC0415
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
    return run_async(
        _auto_prospect_job(uuid.UUID(user_id), uuid.UUID(job_id))
    )


async def _prewarm_job_people(
    user_id: uuid.UUID, job_id: uuid.UUID, target_count_per_bucket: int = 1,
) -> dict:
    """Pre-warm the top contacts for a single job and reveal it in the feed.

    Runs the job-aware people search (1 recruiter + 1 hiring manager + 1 next
    best by default), persists those contacts, and saves the research snapshot
    so opening the job shows people instantly. ALWAYS flips the job's
    people_prewarm_status to "ready" when done — even on failure or zero
    results — so a discovered job is never permanently hidden.
    """
    from sqlalchemy import update  # noqa: PLC0415
    from app.models.job import Job  # noqa: PLC0415
    from app.services.people import search_people_for_job  # noqa: PLC0415
    from app.services.people.serialize import _serialize_people_search_result  # noqa: PLC0415
    from app.services.job_research_snapshot_service import save_job_research_snapshot  # noqa: PLC0415

    stats = {"job_id": str(job_id), "people_found": 0, "snapshot_saved": False}

    async with async_session() as db:
        try:
            result = await search_people_for_job(
                db=db,
                user_id=user_id,
                job_id=job_id,
                target_count_per_bucket=target_count_per_bucket,
            )
            response = _serialize_people_search_result(result)
            stats["people_found"] = (
                len(response.recruiters)
                + len(response.hiring_managers)
                + len(response.peers)
            )
            await save_job_research_snapshot(
                db,
                user_id=user_id,
                job_id=job_id,
                company_name=getattr(result.get("company"), "name", None),
                target_count_per_bucket=target_count_per_bucket,
                recruiters=[r.model_dump(mode="json") for r in response.recruiters],
                hiring_managers=[m.model_dump(mode="json") for m in response.hiring_managers],
                peers=[p.model_dump(mode="json") for p in response.peers],
                your_connections=[c.model_dump(mode="json") for c in response.your_connections],
                errors=[e.model_dump(mode="json") for e in (response.errors or [])] or None,
            )
            stats["snapshot_saved"] = True
        except Exception:
            logger.exception(
                "Job people pre-warm failed: user=%s job=%s", user_id, job_id,
            )
            await db.rollback()

        # Always reveal the job — even on failure / zero results — so it is never
        # permanently hidden. Separate statement so it survives a rolled-back
        # search transaction.
        try:
            await db.execute(
                update(Job)
                .where(Job.id == job_id, Job.user_id == user_id)
                .values(people_prewarm_status="ready")
            )
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to mark job ready after pre-warm: user=%s job=%s",
                user_id, job_id,
            )

    return stats


@celery_app.task(
    name="app.tasks.auto_prospect.prewarm_job_people",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=300,
    max_retries=1,
    soft_time_limit=300,
    time_limit=360,
)
def prewarm_job_people(
    user_id: str, job_id: str, target_count_per_bucket: int = 1,
) -> dict:
    """Celery task: pre-warm a single job's top contacts and reveal it.

    Kept for in-flight compatibility during deploys; new fan-outs queue
    ``prewarm_job_people_batch`` (one task per company group) instead.
    """
    return run_async(
        _prewarm_job_people(
            uuid.UUID(user_id), uuid.UUID(job_id), target_count_per_bucket,
        )
    )


# Self-imposed wall-clock budget for one batch, kept safely under the task's
# soft time limit: when it runs out, the remaining jobs are revealed unwarmed
# instead of tripping the limit mid-search (they behave like the cap-overflow
# tail — visible, with "Find People" still available live).
PREWARM_BATCH_TIME_BUDGET_SECONDS = 780


async def _reveal_jobs(user_id: uuid.UUID, job_ids: list[uuid.UUID]) -> None:
    """Flip jobs back to ready in one statement (never leave them hidden)."""
    from sqlalchemy import update  # noqa: PLC0415
    from app.models.job import Job  # noqa: PLC0415

    if not job_ids:
        return
    async with async_session() as db:
        await db.execute(
            update(Job)
            .where(Job.user_id == user_id, Job.id.in_(job_ids))
            .values(people_prewarm_status="ready")
        )
        await db.commit()


async def _prewarm_job_people_batch(
    user_id: uuid.UUID, job_ids: list[uuid.UUID], target_count_per_bucket: int = 1,
) -> dict:
    """Pre-warm a company-grouped batch of jobs in one task.

    Jobs at the same employer share company resolution, known-people cache and
    search-provider cache hits, so running them consecutively in one worker
    slot is much cheaper than one task (fresh DB connection, task overhead)
    per job. Each job still reveals individually as it completes.
    """
    stats = {"jobs": len(job_ids), "completed": 0, "revealed_unwarmed": 0}
    deadline = time.monotonic() + PREWARM_BATCH_TIME_BUDGET_SECONDS
    for position, job_id in enumerate(job_ids):
        if time.monotonic() > deadline:
            remaining = job_ids[position:]
            try:
                await _reveal_jobs(user_id, remaining)
            except Exception:
                logger.exception(
                    "Failed revealing remaining batch jobs: user=%s", user_id,
                )
            stats["revealed_unwarmed"] = len(remaining)
            logger.warning(
                "Pre-warm batch out of budget: user=%s completed=%d revealed=%d",
                user_id, stats["completed"], len(remaining),
            )
            break
        await _prewarm_job_people(user_id, job_id, target_count_per_bucket)
        stats["completed"] += 1
    return stats


@celery_app.task(
    name="app.tasks.auto_prospect.prewarm_job_people_batch",
    soft_time_limit=900,
    time_limit=960,
)
def prewarm_job_people_batch(
    user_id: str, job_ids: list[str], target_count_per_bucket: int = 1,
) -> dict:
    """Celery task: pre-warm one company group of jobs (see the async impl).

    No retries: every job is flipped ready by the per-job worker or the budget
    guard, and the feed's reveal timeout is the final backstop.
    """
    return run_async(
        _prewarm_job_people_batch(
            uuid.UUID(user_id),
            [uuid.UUID(job_id) for job_id in job_ids],
            target_count_per_bucket,
        )
    )


# A snapshot refreshed within this window is treated as already up to date, so
# a burst of clicks on a stale snapshot doesn't fan out into repeated searches.
SNAPSHOT_REFRESH_DEBOUNCE = timedelta(minutes=2)


async def _refresh_job_research_snapshot(
    user_id: uuid.UUID, job_id: uuid.UUID, target_count_per_bucket: int = 3,
) -> dict:
    """Re-run the job-aware people search and re-save the snapshot.

    Backs the stale-while-revalidate path: the request served the old snapshot
    instantly, this refreshes it so the next visit is fresh. Debounced so
    concurrent stale clicks don't trigger redundant searches.
    """
    from app.services.people import search_people_for_job  # noqa: PLC0415
    from app.services.people.serialize import _serialize_people_search_result  # noqa: PLC0415
    from app.services.job_research_snapshot_service import (  # noqa: PLC0415
        get_job_research_snapshot,
        save_job_research_snapshot,
    )

    stats = {"job_id": str(job_id), "refreshed": False, "skipped": False}

    async with async_session() as db:
        # Debounce: if someone just refreshed this snapshot, don't search again.
        existing = await get_job_research_snapshot(db, user_id=user_id, job_id=job_id)
        if existing and existing.updated_at:
            age = datetime.now(timezone.utc) - existing.updated_at
            if age < SNAPSHOT_REFRESH_DEBOUNCE:
                stats["skipped"] = True
                return stats

        try:
            result = await search_people_for_job(
                db=db,
                user_id=user_id,
                job_id=job_id,
                target_count_per_bucket=target_count_per_bucket,
            )
        except Exception:
            logger.exception(
                "Snapshot refresh search failed: user=%s job=%s", user_id, job_id,
            )
            return stats

        response = _serialize_people_search_result(result)
        try:
            await save_job_research_snapshot(
                db,
                user_id=user_id,
                job_id=job_id,
                company_name=getattr(result.get("company"), "name", None),
                target_count_per_bucket=target_count_per_bucket,
                recruiters=[r.model_dump(mode="json") for r in response.recruiters],
                hiring_managers=[m.model_dump(mode="json") for m in response.hiring_managers],
                peers=[p.model_dump(mode="json") for p in response.peers],
                your_connections=[c.model_dump(mode="json") for c in response.your_connections],
                errors=[e.model_dump(mode="json") for e in (response.errors or [])] or None,
            )
            stats["refreshed"] = True
        except Exception:
            logger.exception(
                "Snapshot refresh save failed: user=%s job=%s", user_id, job_id,
            )

    return stats


@celery_app.task(
    name="app.tasks.auto_prospect.refresh_job_research_snapshot",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=300,
    max_retries=1,
    soft_time_limit=300,
    time_limit=360,
)
def refresh_job_research_snapshot(
    user_id: str, job_id: str, target_count_per_bucket: int = 3,
) -> dict:
    """Celery task: background refresh of a job's people-search snapshot."""
    return run_async(
        _refresh_job_research_snapshot(
            uuid.UUID(user_id), uuid.UUID(job_id), target_count_per_bucket,
        )
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
        "quarantined_count": 0,
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
            # Skip only if a draft already exists for this person AND THIS job
            # (audit M7). Keying on person alone wrongly suppressed drafts for a
            # second job targeting the same contact. job_id lives in the message
            # context_snapshot JSON.
            existing_draft = await db.execute(
                select(Message.id).where(
                    Message.user_id == user_id,
                    Message.person_id == person.id,
                    Message.context_snapshot["job_id"].astext == str(job_id),
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
                            snapshot = (
                                msg_obj.context_snapshot
                                if isinstance(msg_obj.context_snapshot, dict)
                                else {}
                            )
                            review = snapshot.get("security_review") or {}
                            if not review.get("safe_for_automatic_send"):
                                stats["quarantined_count"] += 1
                                continue
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
    return run_async(
        _auto_draft_for_job(uuid.UUID(user_id), uuid.UUID(job_id))
    )


async def _process_pending_sends() -> dict:
    """Send messages whose scheduled_send_at has passed.

    Re-checks auto_send_enabled at send time. If disabled, clears all
    scheduled_send_at timestamps for that user (cancels queue).
    Rate-limited to 10 sends per user per cycle.
    """
    from sqlalchemy import select, distinct, update  # noqa: PLC0415
    from sqlalchemy.exc import ProgrammingError  # noqa: PLC0415
    from app.models.message import Message  # noqa: PLC0415
    from app.models.settings import UserSettings  # noqa: PLC0415
    from app.services.draft_staging_service import (  # noqa: PLC0415
        send_staged_message,
        resolve_connected_provider,
        claim_message_for_send,
    )
    from app.services.notification_service import create_notification  # noqa: PLC0415

    stats = {"sent": 0, "cancelled": 0, "errors": 0}
    now = datetime.now(timezone.utc)

    async def _cancel_queue(db, uid) -> int:
        pending = await db.execute(
            select(Message).where(
                Message.user_id == uid,
                Message.scheduled_send_at.isnot(None),
            )
        )
        count = 0
        for msg in pending.scalars().all():
            msg.scheduled_send_at = None
            count += 1
        return count

    # Discover affected users in a short-lived session.
    async with async_session() as db:
        try:
            user_ids_result = await db.execute(
                select(distinct(Message.user_id)).where(
                    Message.status == "staged",
                    Message.scheduled_send_at.isnot(None),
                    Message.scheduled_send_at <= now,
                )
            )
        except ProgrammingError as exc:
            if not _is_missing_messages_table_error(exc):
                raise
            await db.rollback()
            logger.warning(
                "Skipping process_pending_sends because the messages table is unavailable. "
                "Database migrations may not be applied yet."
            )
            return stats
        user_ids = [row[0] for row in user_ids_result.all()]

    # Process each user in its OWN session so a failure for one user can't poison
    # the shared transaction and starve subsequent users (audit pass-2 P10).
    for uid in user_ids:
        async with async_session() as db:
            try:
                user_settings = (
                    await db.execute(
                        select(UserSettings).where(UserSettings.user_id == uid)
                    )
                ).scalar_one_or_none()

                if not user_settings or not user_settings.auto_send_enabled:
                    stats["cancelled"] += await _cancel_queue(db, uid)
                    await db.commit()
                    continue

                ready_ids = [
                    row[0]
                    for row in (
                        await db.execute(
                            select(Message.id).where(
                                Message.user_id == uid,
                                Message.status == "staged",
                                Message.scheduled_send_at.isnot(None),
                                Message.scheduled_send_at <= now,
                            ).limit(10)
                        )
                    ).all()
                ]

                sent_count = 0
                for msg_id in ready_ids:
                    # Re-check consent + connection right before each send so a
                    # mid-cycle disable/disconnect takes effect immediately
                    # (audit pass-2 P11/P18), not just at the next 5-min tick.
                    still_enabled = (
                        await db.execute(
                            select(UserSettings.auto_send_enabled).where(
                                UserSettings.user_id == uid
                            )
                        )
                    ).scalar_one_or_none()
                    if not still_enabled:
                        stats["cancelled"] += await _cancel_queue(db, uid)
                        await db.commit()
                        break

                    message_result = await db.execute(
                        select(Message).where(Message.id == msg_id, Message.user_id == uid)
                    )
                    message = message_result.scalar_one_or_none()
                    snapshot = (
                        message.context_snapshot
                        if message and isinstance(message.context_snapshot, dict)
                        else {}
                    )
                    review = snapshot.get("security_review") or {}
                    if not review.get("safe_for_automatic_send"):
                        if message:
                            message.scheduled_send_at = None
                        stats["cancelled"] += 1
                        await db.commit()
                        continue

                    provider = await resolve_connected_provider(db, uid)
                    if not provider:
                        stats["cancelled"] += await _cancel_queue(db, uid)
                        await db.commit()
                        await create_notification(
                            db, uid,
                            type="auto_send_failed",
                            title="Auto-send cancelled",
                            body="No email provider connected. Scheduled sends cancelled.",
                        )
                        await db.commit()
                        break

                    # Atomic claim BEFORE the network send (audit pass-2 P2/P5).
                    if not await claim_message_for_send(db, user_id=uid, message_id=msg_id):
                        continue  # lost the race / already handled — never double-send

                    try:
                        await send_staged_message(
                            db=db, user_id=uid, message_id=msg_id, provider=provider,
                        )
                        stats["sent"] += 1
                        sent_count += 1
                    except Exception:
                        stats["errors"] += 1
                        await db.rollback()
                        # Release the claim: back to staged, unscheduled (visible,
                        # not auto-retried, never double-sent).
                        await db.execute(
                            update(Message)
                            .where(
                                Message.id == msg_id,
                                Message.user_id == uid,
                                Message.status == "sending",
                            )
                            .values(status="staged", scheduled_send_at=None)
                        )
                        await db.commit()
                        logger.debug("Auto-send failed: message=%s", msg_id, exc_info=True)

                if sent_count > 0:
                    await create_notification(
                        db, uid,
                        type="auto_send_complete",
                        title="Auto-send complete",
                        body=f"Sent {sent_count} email(s) automatically.",
                    )
                    await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("process_pending_sends failed for user %s", uid)

    return stats


@celery_app.task(
    name="app.tasks.auto_prospect.process_pending_sends",
    soft_time_limit=120,
    time_limit=180,
)
def process_pending_sends() -> dict:
    """Celery beat task: process scheduled auto-sends every 5 minutes."""
    return run_async(_process_pending_sends())
