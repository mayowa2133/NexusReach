"""LinkedIn graph sync sessions, batch imports, status, and cleanup."""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.linkedin_graph import (
    LinkedInGraphConnection,
    LinkedInGraphFollow,
    LinkedInGraphSyncRun,
)
from app.services.linkedin_graph.parsing import parse_linkedin_connections_file
from app.services.linkedin_graph.store import _connection_count, _follow_counts, _get_or_create_user_settings, _token_hash, _upsert_connections, _upsert_follows, _utcnow
from app.services.linkedin_graph.store import graph_freshness_metadata

logger = logging.getLogger(__name__)


SYNC_STATUS_IDLE = "idle"


SYNC_STATUS_AWAITING_UPLOAD = "awaiting_upload"


SYNC_STATUS_SYNCING = "syncing"


SYNC_STATUS_COMPLETED = "completed"


SYNC_STATUS_FAILED = "failed"




async def _latest_run(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> LinkedInGraphSyncRun | None:
    result = await db.execute(
        select(LinkedInGraphSyncRun)
        .where(LinkedInGraphSyncRun.user_id == user_id)
        .order_by(LinkedInGraphSyncRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _serialize_run(run: LinkedInGraphSyncRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "source": run.source,
        "status": run.status,
        "processed_count": run.processed_count,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "session_expires_at": run.session_expires_at,
        "last_error": run.last_error,
    }


async def get_status(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    user_settings = await _get_or_create_user_settings(db, user_id)
    last_run = await _latest_run(db, user_id)
    count = await _connection_count(db, user_id)
    followed_people_count, followed_companies_count = await _follow_counts(db, user_id)
    has_any_graph_data = count > 0 or followed_people_count > 0 or followed_companies_count > 0

    sync_status = user_settings.linkedin_graph_sync_status or SYNC_STATUS_IDLE
    if sync_status == SYNC_STATUS_AWAITING_UPLOAD and last_run and last_run.session_expires_at:
        if last_run.session_expires_at <= _utcnow():
            sync_status = SYNC_STATUS_IDLE

    freshness = graph_freshness_metadata(user_settings.linkedin_graph_last_synced_at)

    return {
        "connected": bool(
            user_settings.linkedin_graph_connected
            and (count > 0 or followed_people_count > 0 or followed_companies_count > 0)
        ),
        "source": user_settings.linkedin_graph_source,
        "last_synced_at": user_settings.linkedin_graph_last_synced_at,
        "sync_status": sync_status,
        "last_error": user_settings.linkedin_graph_last_error,
        "connection_count": count,
        "followed_people_count": followed_people_count,
        "followed_companies_count": followed_companies_count,
        "freshness": freshness["freshness"],
        "days_since_last_sync": freshness["days_since_sync"],
        "refresh_recommended": bool(
            has_any_graph_data
            and freshness["refresh_recommended"]
        ),
        "stale_after_days": freshness["stale_after_days"],
        "recommended_resync_every_days": freshness["recommended_resync_every_days"],
        "status_message": freshness["status_message"] if has_any_graph_data else "No LinkedIn graph data synced yet.",
        "last_run": _serialize_run(last_run),
    }


async def create_sync_session(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    now = _utcnow()
    token = secrets.token_urlsafe(24)
    expires_at = now + timedelta(seconds=settings.linkedin_graph_sync_session_ttl_seconds)

    sync_run = LinkedInGraphSyncRun(
        user_id=user_id,
        source="local_sync",
        status=SYNC_STATUS_AWAITING_UPLOAD,
        session_token_hash=_token_hash(token),
        session_expires_at=expires_at,
        started_at=now,
    )
    db.add(sync_run)

    user_settings = await _get_or_create_user_settings(db, user_id)
    user_settings.linkedin_graph_sync_status = SYNC_STATUS_AWAITING_UPLOAD
    user_settings.linkedin_graph_last_error = None

    await db.commit()
    await db.refresh(sync_run)

    return {
        "sync_run_id": str(sync_run.id),
        "session_token": token,
        "expires_at": expires_at,
        "upload_path": "/api/linkedin-graph/import-batch",
        "max_batch_size": settings.linkedin_graph_max_import_batch_size,
    }


async def _sync_run_for_token(
    db: AsyncSession,
    session_token: str,
) -> LinkedInGraphSyncRun:
    token_hash = _token_hash(session_token)
    now = _utcnow()
    result = await db.execute(
        select(LinkedInGraphSyncRun).where(
            LinkedInGraphSyncRun.session_token_hash == token_hash,
            LinkedInGraphSyncRun.session_expires_at.is_not(None),
            LinkedInGraphSyncRun.session_expires_at > now,
        )
    )
    sync_run = result.scalar_one_or_none()
    if sync_run is None:
        raise ValueError("Invalid or expired LinkedIn graph sync session.")
    return sync_run


async def import_batch_with_session(
    db: AsyncSession,
    session_token: str,
    connections: list[dict[str, Any]],
    *,
    is_final_batch: bool = False,
) -> dict[str, Any]:
    if len(connections) > settings.linkedin_graph_max_import_batch_size:
        raise ValueError(
            f"Batch size exceeds the limit of {settings.linkedin_graph_max_import_batch_size}."
        )

    sync_run = await _sync_run_for_token(db, session_token)
    stats = await _upsert_connections(
        db,
        sync_run.user_id,
        connections,
        source="local_sync",
    )

    now = _utcnow()
    sync_run.processed_count += stats["processed_count"]
    sync_run.created_count += stats["created_count"]
    sync_run.updated_count += stats["updated_count"]
    sync_run.status = SYNC_STATUS_COMPLETED if is_final_batch else SYNC_STATUS_SYNCING
    if is_final_batch:
        sync_run.completed_at = now
        sync_run.session_token_hash = None
        sync_run.session_expires_at = None

    user_settings = await _get_or_create_user_settings(db, sync_run.user_id)
    user_settings.linkedin_graph_connected = (await _connection_count(db, sync_run.user_id)) > 0
    user_settings.linkedin_graph_source = "local_sync"
    user_settings.linkedin_graph_last_synced_at = now
    user_settings.linkedin_graph_sync_status = sync_run.status
    user_settings.linkedin_graph_last_error = None

    await db.commit()
    return await get_status(db, sync_run.user_id)


async def import_follow_batch_with_session(
    db: AsyncSession,
    session_token: str,
    follows: list[dict[str, Any]],
    *,
    is_final_batch: bool = False,
) -> dict[str, Any]:
    if len(follows) > settings.linkedin_graph_max_import_batch_size:
        raise ValueError(
            f"Batch size exceeds the limit of {settings.linkedin_graph_max_import_batch_size}."
        )

    sync_run = await _sync_run_for_token(db, session_token)
    stats = await _upsert_follows(
        db,
        sync_run.user_id,
        follows,
        source="local_sync",
    )

    now = _utcnow()
    sync_run.processed_count += stats["processed_count"]
    sync_run.created_count += stats["created_count"]
    sync_run.updated_count += stats["updated_count"]
    sync_run.status = SYNC_STATUS_COMPLETED if is_final_batch else SYNC_STATUS_SYNCING
    if is_final_batch:
        sync_run.completed_at = now
        sync_run.session_token_hash = None
        sync_run.session_expires_at = None

    user_settings = await _get_or_create_user_settings(db, sync_run.user_id)
    connection_count = await _connection_count(db, sync_run.user_id)
    followed_people_count, followed_companies_count = await _follow_counts(db, sync_run.user_id)
    user_settings.linkedin_graph_connected = (
        connection_count > 0 or followed_people_count > 0 or followed_companies_count > 0
    )
    user_settings.linkedin_graph_source = "local_sync"
    user_settings.linkedin_graph_last_synced_at = now
    user_settings.linkedin_graph_sync_status = sync_run.status
    user_settings.linkedin_graph_last_error = None

    await db.commit()
    return await get_status(db, sync_run.user_id)


async def import_file(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    filename: str | None,
    file_bytes: bytes,
) -> dict[str, Any]:
    sync_run = LinkedInGraphSyncRun(
        user_id=user_id,
        source="manual_import",
        status=SYNC_STATUS_SYNCING,
        started_at=_utcnow(),
    )
    db.add(sync_run)
    user_settings = await _get_or_create_user_settings(db, user_id)
    user_settings.linkedin_graph_sync_status = SYNC_STATUS_SYNCING
    user_settings.linkedin_graph_last_error = None
    await db.flush()

    try:
        rows = parse_linkedin_connections_file(filename, file_bytes)
        stats = await _upsert_connections(db, user_id, rows, source="manual_import")
    except ValueError as exc:
        sync_run.status = SYNC_STATUS_FAILED
        sync_run.last_error = str(exc)
        sync_run.completed_at = _utcnow()
        user_settings.linkedin_graph_sync_status = SYNC_STATUS_FAILED
        user_settings.linkedin_graph_last_error = str(exc)
        await db.commit()
        raise

    now = _utcnow()
    sync_run.processed_count = stats["processed_count"]
    sync_run.created_count = stats["created_count"]
    sync_run.updated_count = stats["updated_count"]
    sync_run.status = SYNC_STATUS_COMPLETED
    sync_run.completed_at = now

    connection_count = await _connection_count(db, user_id)
    user_settings.linkedin_graph_connected = connection_count > 0
    user_settings.linkedin_graph_source = "manual_import"
    user_settings.linkedin_graph_last_synced_at = now
    user_settings.linkedin_graph_sync_status = SYNC_STATUS_COMPLETED
    user_settings.linkedin_graph_last_error = None

    await db.commit()
    return await get_status(db, user_id)


async def clear_connections(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    await db.execute(
        delete(LinkedInGraphConnection).where(LinkedInGraphConnection.user_id == user_id)
    )
    await db.execute(
        delete(LinkedInGraphFollow).where(LinkedInGraphFollow.user_id == user_id)
    )
    await db.execute(
        delete(LinkedInGraphSyncRun).where(LinkedInGraphSyncRun.user_id == user_id)
    )

    user_settings = await _get_or_create_user_settings(db, user_id)
    user_settings.linkedin_graph_connected = False
    user_settings.linkedin_graph_source = None
    user_settings.linkedin_graph_last_synced_at = None
    user_settings.linkedin_graph_sync_status = SYNC_STATUS_IDLE
    user_settings.linkedin_graph_last_error = None

    await db.commit()
    return await get_status(db, user_id)


async def cleanup_orphaned_sync_sessions(db: AsyncSession) -> dict[str, int]:
    """Mark orphaned sync sessions as failed.

    Targets two categories:
    - ``awaiting_upload`` sessions whose ``session_expires_at`` has passed.
    - ``syncing`` sessions that started more than 24 hours ago (stuck).

    Also resets the corresponding ``UserSettings.linkedin_graph_sync_status``
    back to ``idle`` so the user can start a new session.
    """
    now = _utcnow()
    cutoff_syncing = now - timedelta(hours=24)

    # Find orphaned runs
    result = await db.execute(
        select(LinkedInGraphSyncRun).where(
            or_(
                # Expired awaiting_upload sessions
                (
                    LinkedInGraphSyncRun.status == SYNC_STATUS_AWAITING_UPLOAD
                ) & (
                    LinkedInGraphSyncRun.session_expires_at <= now
                ),
                # Stuck syncing sessions (>24h)
                (
                    LinkedInGraphSyncRun.status == SYNC_STATUS_SYNCING
                ) & (
                    LinkedInGraphSyncRun.started_at <= cutoff_syncing
                ),
            )
        )
    )
    orphaned_runs = list(result.scalars().all())

    if not orphaned_runs:
        return {"cleaned_up": 0}

    affected_user_ids: set[uuid.UUID] = set()
    for run in orphaned_runs:
        run.status = SYNC_STATUS_FAILED
        run.last_error = f"Session orphaned — cleaned up at {now.isoformat()}"
        run.completed_at = now
        run.session_token_hash = None
        run.session_expires_at = None
        affected_user_ids.add(run.user_id)

    # Reset user settings sync status for affected users
    for user_id in affected_user_ids:
        user_settings = await _get_or_create_user_settings(db, user_id)
        if user_settings.linkedin_graph_sync_status in (
            SYNC_STATUS_AWAITING_UPLOAD,
            SYNC_STATUS_SYNCING,
        ):
            user_settings.linkedin_graph_sync_status = SYNC_STATUS_IDLE
            user_settings.linkedin_graph_last_error = "Sync session timed out."

    await db.commit()
    return {"cleaned_up": len(orphaned_runs)}
