"""Transactional coalescing: edits during a rescore cannot be lost."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.profile_rescore import ProfileRescoreRequest
from app.utils.resource_limits import consume

logger = logging.getLogger(__name__)
LEASE_SECONDS = 900  # Longer than the task's 240 second hard deadline.


async def admit(user_id: uuid.UUID) -> None:
    await consume([
        ("profile-rescore-global", settings.profile_rescore_hourly_limit, 1),
        (f"profile-rescore-account:{user_id}", settings.profile_rescore_account_hourly_limit, 1),
    ], window=3600)


def _publish(user_id: uuid.UUID, ticket: uuid.UUID) -> None:
    from app.tasks.jobs import rescore_user_jobs

    try:
        rescore_user_jobs.delay(str(user_id), str(ticket))
    except Exception:
        # The durable outbox is recovered by beat if the broker is down.
        logger.warning("Could not publish durable profile rescore", exc_info=True)


async def request(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Commit the profile and its latest request together, then publish once."""
    now = datetime.now(timezone.utc)
    ticket, version = uuid.uuid4(), uuid.uuid4()
    statement = insert(ProfileRescoreRequest).values(
        user_id=user_id, requested_version=version, ticket=ticket,
        lease_until=now + timedelta(seconds=LEASE_SECONDS),
    ).on_conflict_do_update(
        index_elements=[ProfileRescoreRequest.user_id],
        set_={"requested_version": version},
    ).returning(ProfileRescoreRequest)
    row = (await db.execute(statement.execution_options(populate_existing=True))).scalar_one()
    publish = row.ticket == ticket or row.lease_until <= now
    if publish:
        row.ticket = ticket
        row.claimed_at = None
        row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    await db.commit()
    if publish:
        _publish(user_id, ticket)


async def claim(user_id: uuid.UUID, ticket: uuid.UUID) -> uuid.UUID | None:
    async with async_session() as db:
        row = await db.get(ProfileRescoreRequest, user_id, with_for_update=True)
        if row is None or row.ticket != ticket or row.claimed_at is not None:
            return None
        row.claimed_at = datetime.now(timezone.utc)
        row.lease_until = row.claimed_at + timedelta(seconds=LEASE_SECONDS)
        version = row.requested_version
        await db.commit()
        return version


async def finish(user_id: uuid.UUID, ticket: uuid.UUID, version: uuid.UUID) -> None:
    next_ticket = None
    async with async_session() as db:
        row = await db.get(ProfileRescoreRequest, user_id, with_for_update=True)
        if row is None or row.ticket != ticket:
            return
        if row.requested_version == version:
            await db.delete(row)
        else:
            # An edit arrived during processing. Keep a single follow-up task
            # which reads the latest profile, rather than one task per edit.
            row.ticket = next_ticket = uuid.uuid4()
            row.claimed_at = None
            row.lease_until = datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)
        await db.commit()
    if next_ticket is not None:
        _publish(user_id, next_ticket)


async def recover() -> int:
    tickets = []
    async with async_session() as db:
        rows = (await db.scalars(select(ProfileRescoreRequest).where(
            ProfileRescoreRequest.lease_until <= datetime.now(timezone.utc),
        ).order_by(ProfileRescoreRequest.lease_until).limit(100).with_for_update(skip_locked=True))).all()
        for row in rows:
            row.ticket = uuid.uuid4()
            row.claimed_at = None
            row.lease_until = datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)
            tickets.append((row.user_id, row.ticket))
        await db.commit()
    for user_id, ticket in tickets:
        _publish(user_id, ticket)
    return len(tickets)
