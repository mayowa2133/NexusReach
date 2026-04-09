"""LinkedIn graph import, sync-session, and warm-path helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.linkedin_graph import LinkedInGraphConnection, LinkedInGraphSyncRun
from app.models.settings import UserSettings
from app.utils.company_identity import (
    extract_public_identity_hints,
    is_ambiguous_company_name,
    normalize_company_name,
)
from app.utils.linkedin import normalize_linkedin_url

CSV_EXTENSIONS = {".csv"}
ZIP_EXTENSIONS = {".zip"}
SYNC_STATUS_IDLE = "idle"
SYNC_STATUS_AWAITING_UPLOAD = "awaiting_upload"
SYNC_STATUS_SYNCING = "syncing"
SYNC_STATUS_COMPLETED = "completed"
SYNC_STATUS_FAILED = "failed"
LINKEDIN_GRAPH_SOURCES = {"local_sync", "manual_import"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _canonicalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        _canonicalize_header(key): value
        for key, value in row.items()
        if _canonicalize_header(key)
    }


def _lookup_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        text = _clean_text(value)
        if text:
            return text
    return ""


def _linkedin_slug_from_url(url: str | None) -> str | None:
    normalized = normalize_linkedin_url(url)
    if not normalized:
        return None
    return normalized.rstrip("/").rsplit("/", 1)[-1]


def _normalize_company_linkedin_url(url: str | None) -> str | None:
    clean = _clean_text(url)
    if not clean:
        return None
    if clean.startswith("linkedin.com") or clean.startswith("www.linkedin.com"):
        clean = f"https://{clean}"
    hints = extract_public_identity_hints(clean)
    if hints.get("page_type") != "linkedin_company":
        return clean
    company_slug = hints.get("company_slug")
    if not company_slug:
        return clean
    return f"https://www.linkedin.com/company/{company_slug}"


def _company_slug_from_url(url: str | None) -> str | None:
    normalized = _normalize_company_linkedin_url(url)
    if not normalized:
        return None
    hints = extract_public_identity_hints(normalized)
    slug = hints.get("company_slug")
    return slug.lower() if isinstance(slug, str) and slug else None


def normalize_connection_payload(
    payload: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    if source not in LINKEDIN_GRAPH_SOURCES:
        raise ValueError(f"Unsupported LinkedIn graph source: {source}")

    row = _canonicalize_row(payload)
    full_name = _lookup_value(row, "full_name", "name")
    if not full_name:
        first_name = _lookup_value(row, "first_name", "firstname")
        last_name = _lookup_value(row, "last_name", "lastname")
        full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if not full_name:
        return None

    linkedin_url = normalize_linkedin_url(
        _lookup_value(row, "linkedin_url", "profile_url", "url")
    )
    company_linkedin_url = _normalize_company_linkedin_url(
        _lookup_value(row, "company_linkedin_url", "company_url", "company_profile_url")
    )
    current_company_name = _lookup_value(
        row,
        "current_company_name",
        "company_name",
        "company",
    )
    headline = _lookup_value(row, "headline", "position", "title")
    normalized_company_name = normalize_company_name(current_company_name) or None

    return {
        "linkedin_url": linkedin_url,
        "linkedin_slug": _linkedin_slug_from_url(linkedin_url),
        "display_name": full_name,
        "headline": headline or None,
        "current_company_name": current_company_name or None,
        "normalized_company_name": normalized_company_name,
        "company_linkedin_url": company_linkedin_url,
        "company_linkedin_slug": _company_slug_from_url(company_linkedin_url),
        "source": source,
    }


def dedupe_connection_candidates(
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    by_slug: dict[str, dict[str, Any]] = {}
    by_name_company: dict[tuple[str, str], dict[str, Any]] = {}

    for raw in rows:
        normalized = normalize_connection_payload(raw, source=source)
        if not normalized:
            continue

        slug = normalized.get("linkedin_slug")
        name_company_key: tuple[str, str] | None = None
        if normalized.get("display_name") and normalized.get("normalized_company_name"):
            name_company_key = (
                normalized["display_name"].strip().lower(),
                normalized["normalized_company_name"],
            )

        target = None
        if slug:
            target = by_slug.get(slug)
        if target is None and name_company_key:
            target = by_name_company.get(name_company_key)

        if target is None:
            deduped.append(normalized)
            if slug:
                by_slug[slug] = normalized
            if name_company_key:
                by_name_company[name_company_key] = normalized
            continue

        for key, value in normalized.items():
            if value and not target.get(key):
                target[key] = value
        if slug and slug not in by_slug:
            by_slug[slug] = target
        if name_company_key and name_company_key not in by_name_company:
            by_name_company[name_company_key] = target

    return deduped


def _find_csv_header_index(lines: list[list[str]]) -> int | None:
    for index, row in enumerate(lines[:25]):
        headers = {_canonicalize_header(cell) for cell in row if _canonicalize_header(cell)}
        has_name = "first_name" in headers and "last_name" in headers
        has_profile = any(key in headers for key in ("url", "profile_url", "linkedin_url"))
        if has_name and has_profile:
            return index
    return None


def parse_linkedin_connections_csv(file_bytes: bytes) -> list[dict[str, Any]]:
    decoded = file_bytes.decode("utf-8-sig", errors="replace")
    csv_rows = list(csv.reader(io.StringIO(decoded)))
    header_index = _find_csv_header_index(csv_rows)
    if header_index is None:
        raise ValueError("Could not find a LinkedIn connections CSV header.")

    header = csv_rows[header_index]
    payload_rows: list[dict[str, Any]] = []
    for row in csv_rows[header_index + 1:]:
        if not any(_clean_text(value) for value in row):
            continue
        payload_rows.append(
            {
                header[position]: row[position] if position < len(row) else ""
                for position in range(len(header))
            }
        )

    return dedupe_connection_candidates(payload_rows, source="manual_import")


def _zip_connection_candidates(names: list[str]) -> list[str]:
    return sorted(
        [
            name
            for name in names
            if name.lower().endswith(".csv")
            and "connections" in PurePosixPath(name).name.lower()
        ],
        key=lambda name: (
            0 if PurePosixPath(name).name.lower() == "connections.csv" else 1,
            len(name),
            name.lower(),
        ),
    )


def parse_linkedin_connections_zip(file_bytes: bytes) -> list[dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid LinkedIn data export ZIP.") from exc

    with archive:
        candidates = _zip_connection_candidates(archive.namelist())
        if not candidates:
            raise ValueError("No LinkedIn connections CSV was found in the ZIP export.")
        with archive.open(candidates[0]) as extracted:
            return parse_linkedin_connections_csv(extracted.read())


def parse_linkedin_connections_file(filename: str | None, file_bytes: bytes) -> list[dict[str, Any]]:
    suffix = PurePosixPath(filename or "").suffix.lower()
    if suffix in CSV_EXTENSIONS:
        return parse_linkedin_connections_csv(file_bytes)
    if suffix in ZIP_EXTENSIONS:
        return parse_linkedin_connections_zip(file_bytes)
    raise ValueError("Upload a LinkedIn connections CSV or ZIP export.")


async def _get_or_create_user_settings(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> UserSettings:
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    user_settings = result.scalar_one_or_none()
    if user_settings is None:
        user_settings = UserSettings(user_id=user_id)
        db.add(user_settings)
        await db.flush()
    return user_settings


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _find_existing_connection(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: dict[str, Any],
) -> LinkedInGraphConnection | None:
    linkedin_slug = payload.get("linkedin_slug")
    if linkedin_slug:
        result = await db.execute(
            select(LinkedInGraphConnection).where(
                LinkedInGraphConnection.user_id == user_id,
                LinkedInGraphConnection.linkedin_slug == linkedin_slug,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

    display_name = _clean_text(payload.get("display_name")).lower()
    normalized_company_name = payload.get("normalized_company_name")
    if display_name and normalized_company_name:
        result = await db.execute(
            select(LinkedInGraphConnection).where(
                LinkedInGraphConnection.user_id == user_id,
                LinkedInGraphConnection.normalized_company_name == normalized_company_name,
                func.lower(LinkedInGraphConnection.display_name) == display_name,
            )
        )
        return result.scalar_one_or_none()

    return None


def _merge_connection(existing: LinkedInGraphConnection, payload: dict[str, Any], *, now: datetime) -> None:
    existing.linkedin_url = payload.get("linkedin_url") or existing.linkedin_url
    existing.linkedin_slug = payload.get("linkedin_slug") or existing.linkedin_slug
    existing.display_name = payload.get("display_name") or existing.display_name
    existing.headline = payload.get("headline") or existing.headline
    existing.current_company_name = payload.get("current_company_name") or existing.current_company_name
    existing.normalized_company_name = (
        payload.get("normalized_company_name") or existing.normalized_company_name
    )
    existing.company_linkedin_url = payload.get("company_linkedin_url") or existing.company_linkedin_url
    existing.company_linkedin_slug = payload.get("company_linkedin_slug") or existing.company_linkedin_slug
    existing.source = payload.get("source") or existing.source
    existing.last_seen_at = now
    existing.last_synced_at = now


async def _upsert_connections(
    db: AsyncSession,
    user_id: uuid.UUID,
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> dict[str, int]:
    now = _utcnow()
    processed_count = 0
    created_count = 0
    updated_count = 0

    for payload in dedupe_connection_candidates(rows, source=source):
        processed_count += 1
        existing = await _find_existing_connection(db, user_id, payload)
        if existing is not None:
            _merge_connection(existing, payload, now=now)
            updated_count += 1
            continue

        db.add(
            LinkedInGraphConnection(
                user_id=user_id,
                linkedin_url=payload.get("linkedin_url"),
                linkedin_slug=payload.get("linkedin_slug"),
                display_name=payload["display_name"],
                headline=payload.get("headline"),
                current_company_name=payload.get("current_company_name"),
                normalized_company_name=payload.get("normalized_company_name"),
                company_linkedin_url=payload.get("company_linkedin_url"),
                company_linkedin_slug=payload.get("company_linkedin_slug"),
                source=source,
                first_seen_at=now,
                last_seen_at=now,
                last_synced_at=now,
            )
        )
        created_count += 1

    return {
        "processed_count": processed_count,
        "created_count": created_count,
        "updated_count": updated_count,
    }


async def _connection_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(LinkedInGraphConnection).where(
            LinkedInGraphConnection.user_id == user_id
        )
    )
    return int(result.scalar() or 0)


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

    sync_status = user_settings.linkedin_graph_sync_status or SYNC_STATUS_IDLE
    if sync_status == SYNC_STATUS_AWAITING_UPLOAD and last_run and last_run.session_expires_at:
        if last_run.session_expires_at <= _utcnow():
            sync_status = SYNC_STATUS_IDLE

    return {
        "connected": bool(user_settings.linkedin_graph_connected and count > 0),
        "source": user_settings.linkedin_graph_source,
        "last_synced_at": user_settings.linkedin_graph_last_synced_at,
        "sync_status": sync_status,
        "last_error": user_settings.linkedin_graph_last_error,
        "connection_count": count,
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


async def get_connections_for_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> list[LinkedInGraphConnection]:
    normalized_company_name = normalize_company_name(company_name)
    trusted_slugs = [slug.strip().lower() for slug in (public_identity_slugs or []) if slug]
    query = select(LinkedInGraphConnection).where(
        LinkedInGraphConnection.user_id == user_id
    )

    if is_ambiguous_company_name(company_name):
        if not trusted_slugs:
            return []
        query = query.where(
            LinkedInGraphConnection.company_linkedin_slug.in_(trusted_slugs)
        )
    else:
        company_filters = []
        if normalized_company_name:
            company_filters.append(
                LinkedInGraphConnection.normalized_company_name == normalized_company_name
            )
        if trusted_slugs:
            company_filters.append(
                LinkedInGraphConnection.company_linkedin_slug.in_(trusted_slugs)
            )
        if not company_filters:
            return []
        query = query.where(or_(*company_filters))

    query = query.order_by(
        LinkedInGraphConnection.display_name.asc(),
        LinkedInGraphConnection.id.asc(),
    ).limit(10)
    result = await db.execute(query)
    return [
        connection
        for connection in result.scalars().all()
        if connection_matches_company(
            connection,
            company_name=company_name,
            public_identity_slugs=public_identity_slugs,
        )
    ]


async def get_connections_by_linkedin_slugs(
    db: AsyncSession,
    user_id: uuid.UUID,
    slugs: list[str],
) -> list[LinkedInGraphConnection]:
    normalized_slugs = sorted({slug.strip().lower() for slug in slugs if slug})
    if not normalized_slugs:
        return []

    result = await db.execute(
        select(LinkedInGraphConnection).where(
            LinkedInGraphConnection.user_id == user_id,
            LinkedInGraphConnection.linkedin_slug.in_(normalized_slugs),
        )
    )
    return list(result.scalars().all())


def serialize_connection(
    connection: LinkedInGraphConnection | dict[str, Any],
    *,
    relevance_score: int | None = None,
    relevance_label: str | None = None,
) -> dict[str, Any]:
    if isinstance(connection, dict):
        connection_id = connection.get("id")
        result = {
            "id": str(connection_id) if connection_id is not None else "",
            "display_name": connection.get("display_name") or "",
            "headline": connection.get("headline"),
            "current_company_name": connection.get("current_company_name"),
            "linkedin_url": connection.get("linkedin_url"),
            "company_linkedin_url": connection.get("company_linkedin_url"),
            "source": connection.get("source") or "manual_import",
            "last_synced_at": connection.get("last_synced_at"),
        }
    else:
        result = {
            "id": str(connection.id),
            "display_name": connection.display_name,
            "headline": connection.headline,
            "current_company_name": connection.current_company_name,
            "linkedin_url": connection.linkedin_url,
            "company_linkedin_url": connection.company_linkedin_url,
            "source": connection.source,
            "last_synced_at": connection.last_synced_at,
        }
    if relevance_score is not None:
        result["relevance_score"] = relevance_score
        result["relevance_label"] = relevance_label
    return result


def connection_matches_company(
    connection: LinkedInGraphConnection | dict[str, Any],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> bool:
    normalized_company_name = normalize_company_name(company_name)
    trusted_slugs = [slug.strip().lower() for slug in (public_identity_slugs or []) if slug]

    company_slug = (
        connection.get("company_linkedin_slug")
        if isinstance(connection, dict)
        else connection.company_linkedin_slug
    )
    connection_company_name = (
        connection.get("normalized_company_name")
        if isinstance(connection, dict)
        else connection.normalized_company_name
    )

    if is_ambiguous_company_name(company_name):
        return bool(company_slug and company_slug in trusted_slugs)

    if connection_company_name and connection_company_name == normalized_company_name:
        return True
    return bool(company_slug and company_slug in trusted_slugs)


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


def _warm_path_priority(person: Any) -> int:
    return {
        "direct_connection": 0,
        "same_company_bridge": 1,
    }.get(getattr(person, "warm_path_type", None), 2)


def apply_warm_path_annotations(
    bucketed: dict[str, list[Any]],
    *,
    company_name: str,
    your_connections: list[LinkedInGraphConnection],
    direct_connections: list[LinkedInGraphConnection] | None = None,
    job_context: Any | None = None,
    connection_scores: dict[str, tuple[int, Any, str]] | None = None,
) -> None:
    from app.utils.connection_relevance import generate_warm_path_reason, parse_headline

    by_slug = {
        connection.linkedin_slug: connection
        for connection in (direct_connections or your_connections)
        if connection.linkedin_slug
    }

    # Pick the best bridge: highest relevance score if available, else first
    bridge_connection: LinkedInGraphConnection | None = None
    if your_connections:
        if connection_scores:
            bridge_connection = max(
                your_connections,
                key=lambda c: connection_scores.get(str(c.id), (0,))[0],
            )
        else:
            bridge_connection = your_connections[0]
    bridge_company_name = bridge_connection.current_company_name if bridge_connection else company_name

    # Pre-parse bridge headline for reason generation
    bridge_signals = parse_headline(bridge_connection.headline) if bridge_connection else None

    for people in bucketed.values():
        for person in people:
            setattr(person, "warm_path_type", None)
            setattr(person, "warm_path_reason", None)
            setattr(person, "warm_path_connection", None)

            person_slug = _linkedin_slug_from_url(getattr(person, "linkedin_url", None))
            direct_connection = by_slug.get(person_slug) if person_slug else None
            if direct_connection is not None:
                setattr(person, "warm_path_type", "direct_connection")
                if job_context:
                    signals = parse_headline(direct_connection.headline)
                    reason = generate_warm_path_reason(
                        direct_connection.display_name,
                        direct_connection.headline,
                        signals,
                        company_name,
                        job_context,
                        is_direct=True,
                    )
                else:
                    reason = f"You are already connected to {direct_connection.display_name} on LinkedIn."
                setattr(person, "warm_path_reason", reason)
                setattr(person, "warm_path_connection", direct_connection)
                continue

            if bridge_connection is None:
                continue

            setattr(person, "warm_path_type", "same_company_bridge")
            if job_context and bridge_signals:
                reason = generate_warm_path_reason(
                    bridge_connection.display_name,
                    bridge_connection.headline,
                    bridge_signals,
                    bridge_company_name or company_name,
                    job_context,
                    is_direct=False,
                )
            else:
                reason = f"You already know {bridge_connection.display_name} at {bridge_company_name or company_name}."
            setattr(person, "warm_path_reason", reason)
            setattr(person, "warm_path_connection", bridge_connection)
