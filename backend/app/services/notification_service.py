"""Notification service — create, list, and manage notifications."""

import uuid

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    type: str,
    title: str,
    body: str | None = None,
    job_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
) -> Notification:
    """Create a new notification."""
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        job_id=job_id,
        company_id=company_id,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


async def get_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    """List notifications for a user, newest first."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read == False)  # noqa: E712
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_unread_count(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    """Count unread notifications."""
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read == False)  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one()


async def mark_notifications_read(
    db: AsyncSession,
    user_id: uuid.UUID,
    notification_ids: list[uuid.UUID],
) -> int:
    """Mark specific notifications as read. Returns count updated."""
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.id.in_(notification_ids),
        )
        .values(read=True)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount


async def mark_all_read(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    """Mark all notifications as read for a user."""
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read == False,  # noqa: E712
        )
        .values(read=True)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount
