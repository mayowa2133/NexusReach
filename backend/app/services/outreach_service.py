"""Outreach tracker service — CRM for networking interactions."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.outreach import OutreachLog
from app.models.person import Person


VALID_STATUSES = {"draft", "sent", "connected", "responded", "met", "following_up", "closed"}


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
    await db.refresh(log)
    return log


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

    for key, value in updates.items():
        if value is not None and hasattr(log, key):
            setattr(log, key, value)

    await db.commit()
    await db.refresh(log)
    return log


async def get_outreach_logs(
    db: AsyncSession,
    user_id: uuid.UUID,
    status: str | None = None,
    person_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
) -> list[OutreachLog]:
    """List outreach logs with optional filters."""
    query = (
        select(OutreachLog)
        .where(OutreachLog.user_id == user_id)
        .options(selectinload(OutreachLog.person))
        .order_by(OutreachLog.updated_at.desc())
    )

    if status:
        query = query.where(OutreachLog.status == status)
    if person_id:
        query = query.where(OutreachLog.person_id == person_id)
    if job_id:
        query = query.where(OutreachLog.job_id == job_id)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_outreach_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    log_id: uuid.UUID,
) -> OutreachLog | None:
    """Get a single outreach log by ID."""
    result = await db.execute(
        select(OutreachLog)
        .where(OutreachLog.id == log_id, OutreachLog.user_id == user_id)
        .options(selectinload(OutreachLog.person))
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
        .options(selectinload(OutreachLog.person))
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
            OutreachLog.next_follow_up_at.isnot(None),
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
