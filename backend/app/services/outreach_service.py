"""Outreach tracker service — CRM for networking interactions."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job import Job
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person


VALID_STATUSES = {"draft", "sent", "connected", "responded", "met", "following_up", "closed"}


async def _assert_owned_references(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    job_id: uuid.UUID | None,
    message_id: uuid.UUID | None,
) -> None:
    """Reject cross-user job_id/message_id references (audit pass-2 P9).

    Outreach logs are user-scoped, but job_id/message_id were previously stored
    without verifying ownership — letting a user attach another user's job or
    message id (and, once P1's eager-loaded relationships exist, surface that
    job's title cross-user).
    """
    if job_id is not None:
        owned = await db.execute(
            select(Job.id).where(Job.id == job_id, Job.user_id == user_id)
        )
        if owned.scalar_one_or_none() is None:
            raise ValueError("Job not found.")
    if message_id is not None:
        owned = await db.execute(
            select(Message.id).where(Message.id == message_id, Message.user_id == user_id)
        )
        if owned.scalar_one_or_none() is None:
            raise ValueError("Message not found.")


def _outreach_load_options():
    """Eager-load every relationship the response serializer touches.

    ``_to_response`` reads ``log.person``, ``log.person.company`` and ``log.job``.
    In async SQLAlchemy, accessing an un-eager-loaded relationship triggers a
    lazy load that raises ``MissingGreenlet`` and 500s the request (audit pass-2
    P1). Loading them up front keeps the serializer crash-free.
    """
    return (
        selectinload(OutreachLog.person).selectinload(Person.company),
        selectinload(OutreachLog.job),
    )


async def _reload_with_relations(
    db: AsyncSession, user_id: uuid.UUID, log_id: uuid.UUID
) -> OutreachLog:
    """Re-fetch a log with serializer relationships eager-loaded (audit pass-2 P1)."""
    result = await db.execute(
        select(OutreachLog)
        .where(OutreachLog.id == log_id, OutreachLog.user_id == user_id)
        .options(*_outreach_load_options())
    )
    return result.scalar_one()


async def create_outreach_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    status: str = "draft",
    channel: str | None = None,
    notes: str | None = None,
    job_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    last_contacted_at: datetime | None = None,
    next_follow_up_at: datetime | None = None,
) -> OutreachLog:
    """Create a new outreach log entry."""
    # Validate person exists and belongs to user
    result = await db.execute(
        select(Person).where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise ValueError("Person not found.")

    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    await _assert_owned_references(db, user_id, job_id=job_id, message_id=message_id)

    log = OutreachLog(
        user_id=user_id,
        person_id=person_id,
        job_id=job_id,
        message_id=message_id,
        status=status,
        channel=channel,
        notes=notes,
        last_contacted_at=last_contacted_at or datetime.now(timezone.utc),
        next_follow_up_at=next_follow_up_at,
    )
    db.add(log)
    await db.commit()
    return await _reload_with_relations(db, user_id, log.id)


async def update_outreach_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    log_id: uuid.UUID,
    **updates: object,
) -> OutreachLog:
    """Update an outreach log entry."""
    result = await db.execute(
        select(OutreachLog).where(
            OutreachLog.id == log_id, OutreachLog.user_id == user_id
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        raise ValueError("Outreach log not found.")

    if "status" in updates and updates["status"] is not None:
        if updates["status"] not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {updates['status']}")

    await _assert_owned_references(
        db,
        user_id,
        job_id=updates.get("job_id") if isinstance(updates.get("job_id"), uuid.UUID) else None,
        message_id=updates.get("message_id") if isinstance(updates.get("message_id"), uuid.UUID) else None,
    )

    for key, value in updates.items():
        if value is not None and hasattr(log, key):
            setattr(log, key, value)

    await db.commit()
    return await _reload_with_relations(db, user_id, log.id)


async def get_outreach_logs(
    db: AsyncSession,
    user_id: uuid.UUID,
    status: str | None = None,
    person_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[OutreachLog], int]:
    """List outreach logs with optional filters and pagination.

    Returns ``(logs, total_count)``.
    """
    from app.utils.pagination import paginate

    query = (
        select(OutreachLog)
        .where(OutreachLog.user_id == user_id)
        .options(*_outreach_load_options())
        .order_by(OutreachLog.updated_at.desc())
    )

    if status:
        query = query.where(OutreachLog.status == status)
    if person_id:
        query = query.where(OutreachLog.person_id == person_id)
    if job_id:
        query = query.where(OutreachLog.job_id == job_id)

    return await paginate(db, query, limit=limit, offset=offset)


async def get_outreach_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    log_id: uuid.UUID,
) -> OutreachLog | None:
    """Get a single outreach log by ID."""
    result = await db.execute(
        select(OutreachLog)
        .where(OutreachLog.id == log_id, OutreachLog.user_id == user_id)
        .options(*_outreach_load_options())
    )
    return result.scalar_one_or_none()


async def get_outreach_timeline(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
) -> list[OutreachLog]:
    """Get all outreach logs for a specific person, ordered chronologically."""
    result = await db.execute(
        select(OutreachLog)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.person_id == person_id,
        )
        .options(*_outreach_load_options())
        .order_by(OutreachLog.created_at.desc())
    )
    return list(result.scalars().all())


async def get_outreach_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Get aggregate outreach statistics."""
    # Total contacts (distinct persons)
    total_result = await db.execute(
        select(sa_func.count(sa_func.distinct(OutreachLog.person_id))).where(
            OutreachLog.user_id == user_id
        )
    )
    total_contacts = total_result.scalar() or 0

    # Count by status
    all_logs_result = await db.execute(
        select(OutreachLog.status, sa_func.count()).where(
            OutreachLog.user_id == user_id
        ).group_by(OutreachLog.status)
    )
    by_status = {row[0]: row[1] for row in all_logs_result.all()}

    # Response rate
    total_sent = sum(
        v for k, v in by_status.items() if k != "draft"
    )
    responded_count = sum(
        v for k, v in by_status.items() if k in ("responded", "met", "closed")
    )
    response_rate = (responded_count / total_sent * 100) if total_sent > 0 else 0.0

    # Upcoming follow-ups
    now = datetime.now(timezone.utc)
    follow_up_result = await db.execute(
        select(sa_func.count()).where(
            OutreachLog.user_id == user_id,
            OutreachLog.next_follow_up_at.is_not(None),
            OutreachLog.next_follow_up_at >= now,
            OutreachLog.status.notin_(["closed"]),
        )
    )
    upcoming_follow_ups = follow_up_result.scalar() or 0

    return {
        "total_contacts": total_contacts,
        "by_status": by_status,
        "response_rate": round(response_rate, 1),
        "upcoming_follow_ups": upcoming_follow_ups,
    }


async def delete_outreach_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    log_id: uuid.UUID,
) -> None:
    """Delete an outreach log entry."""
    result = await db.execute(
        select(OutreachLog).where(
            OutreachLog.id == log_id, OutreachLog.user_id == user_id
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        raise ValueError("Outreach log not found.")

    await db.delete(log)
    await db.commit()
