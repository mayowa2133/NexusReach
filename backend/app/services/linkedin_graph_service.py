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
from app.models.linkedin_graph import (
    LinkedInGraphConnection,
    LinkedInGraphFollow,
    LinkedInGraphSyncRun,
)
from app.models.settings import UserSettings
from app.utils.company_identity import (
    company_family,
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
FOLLOW_ENTITY_TYPES = {"person", "company"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def graph_freshness_metadata(last_synced_at: datetime | None) -> dict[str, Any]:
    recommended_days = settings.linkedin_graph_refresh_recommended_days
    stale_after_days = settings.linkedin_graph_stale_after_days

    if last_synced_at is None:
        return {
            "freshness": "empty",
            "days_since_sync": None,
            "refresh_recommended": False,
            "stale": False,
            "caution": None,
            "status_message": "No LinkedIn graph data synced yet.",
            "recommended_resync_every_days": recommended_days,
            "stale_after_days": stale_after_days,
        }

    days_since_sync = max(
        0,
        int((_utcnow() - last_synced_at).total_seconds() // 86400),
    )
    refresh_recommended = days_since_sync >= recommended_days
    stale = days_since_sync >= stale_after_days
    freshness = "fresh"
    caution = None
    status_message = (
        f"LinkedIn graph is current. Re-sync every {recommended_days} days."
    )

    if stale:
        freshness = "stale"
        caution = (
            f"LinkedIn graph data is {days_since_sync} days old. Confirm mutual connections"
            " before relying on them in outreach."
        )
        status_message = (
            f"LinkedIn graph is stale ({days_since_sync} days old). Re-sync before using warm paths heavily."
        )
    elif refresh_recommended:
        freshness = "aging"
        caution = (
            f"LinkedIn graph data is {days_since_sync} days old. A re-sync is recommended"
            " before high-priority outreach."
        )
        status_message = (
            f"LinkedIn graph is aging ({days_since_sync} days since last sync). Re-sync soon."
        )

    return {
        "freshness": freshness,
        "days_since_sync": days_since_sync,
        "refresh_recommended": refresh_recommended,
        "stale": stale,
        "caution": caution,
        "status_message": status_message,
        "recommended_resync_every_days": recommended_days,
        "stale_after_days": stale_after_days,
    }


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


def normalize_follow_payload(
    payload: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    if source not in LINKEDIN_GRAPH_SOURCES:
        raise ValueError(f"Unsupported LinkedIn graph source: {source}")

    row = _canonicalize_row(payload)
    entity_type = _lookup_value(row, "entity_type").lower()
    if entity_type not in FOLLOW_ENTITY_TYPES:
        return None

    display_name = _lookup_value(row, "display_name", "full_name", "name")
    if not display_name:
        return None

    raw_url = _lookup_value(row, "linkedin_url", "profile_url", "url")
    company_url = _lookup_value(
        row,
        "company_linkedin_url",
        "company_profile_url",
        "company_url",
    )
    headline = _lookup_value(row, "headline", "position", "title")
    current_company_name = _lookup_value(
        row,
        "current_company_name",
        "company_name",
        "company",
    )

    if entity_type == "company":
        linkedin_url = _normalize_company_linkedin_url(raw_url)
        linkedin_slug = _company_slug_from_url(linkedin_url)
        normalized_company_name = normalize_company_name(display_name) or None
        current_company_name = display_name
        company_linkedin_url = linkedin_url
        company_linkedin_slug = linkedin_slug
    else:
        linkedin_url = normalize_linkedin_url(raw_url)
        linkedin_slug = _linkedin_slug_from_url(linkedin_url)
        company_linkedin_url = _normalize_company_linkedin_url(company_url)
        company_linkedin_slug = _company_slug_from_url(company_linkedin_url)
        normalized_company_name = normalize_company_name(current_company_name) or None

    return {
        "entity_type": entity_type,
        "linkedin_url": linkedin_url,
        "linkedin_slug": linkedin_slug,
        "display_name": display_name,
        "headline": headline or None,
        "current_company_name": current_company_name or None,
        "normalized_company_name": normalized_company_name,
        "company_linkedin_url": company_linkedin_url,
        "company_linkedin_slug": company_linkedin_slug,
        "source": source,
    }


def dedupe_follow_candidates(
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    by_type_slug: dict[tuple[str, str], dict[str, Any]] = {}
    by_type_name: dict[tuple[str, str], dict[str, Any]] = {}

    for raw in rows:
        normalized = normalize_follow_payload(raw, source=source)
        if not normalized:
            continue

        entity_type = normalized["entity_type"]
        slug = normalized.get("linkedin_slug")
        display_name = _clean_text(normalized.get("display_name")).lower()
        target = by_type_slug.get((entity_type, slug)) if slug else None
        if target is None and display_name:
            target = by_type_name.get((entity_type, display_name))

        if target is None:
            deduped.append(normalized)
            if slug:
                by_type_slug[(entity_type, slug)] = normalized
            if display_name:
                by_type_name[(entity_type, display_name)] = normalized
            continue

        for key, value in normalized.items():
            if value and not target.get(key):
                target[key] = value
        if slug and (entity_type, slug) not in by_type_slug:
            by_type_slug[(entity_type, slug)] = target
        if display_name and (entity_type, display_name) not in by_type_name:
            by_type_name[(entity_type, display_name)] = target

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


async def _find_existing_follow(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: dict[str, Any],
) -> LinkedInGraphFollow | None:
    entity_type = payload.get("entity_type")
    linkedin_slug = payload.get("linkedin_slug")
    if entity_type and linkedin_slug:
        result = await db.execute(
            select(LinkedInGraphFollow).where(
                LinkedInGraphFollow.user_id == user_id,
                LinkedInGraphFollow.entity_type == entity_type,
                LinkedInGraphFollow.linkedin_slug == linkedin_slug,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

    display_name = _clean_text(payload.get("display_name")).lower()
    if entity_type and display_name:
        result = await db.execute(
            select(LinkedInGraphFollow).where(
                LinkedInGraphFollow.user_id == user_id,
                LinkedInGraphFollow.entity_type == entity_type,
                func.lower(LinkedInGraphFollow.display_name) == display_name,
            )
        )
        return result.scalar_one_or_none()

    return None


def _merge_follow(existing: LinkedInGraphFollow, payload: dict[str, Any], *, now: datetime) -> None:
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


async def _upsert_follows(
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

    for payload in dedupe_follow_candidates(rows, source=source):
        processed_count += 1
        existing = await _find_existing_follow(db, user_id, payload)
        if existing is not None:
            _merge_follow(existing, payload, now=now)
            updated_count += 1
            continue

        db.add(
            LinkedInGraphFollow(
                user_id=user_id,
                entity_type=payload["entity_type"],
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


async def _follow_counts(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    result = await db.execute(
        select(
            LinkedInGraphFollow.entity_type,
            func.count(LinkedInGraphFollow.id),
        )
        .where(LinkedInGraphFollow.user_id == user_id)
        .group_by(LinkedInGraphFollow.entity_type)
    )
    counts = {entity_type: int(count or 0) for entity_type, count in result.all()}
    return counts.get("person", 0), counts.get("company", 0)


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


async def get_connections_for_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> list[LinkedInGraphConnection]:
    normalized_company_name = normalize_company_name(company_name)
    trusted_slugs = [slug.strip().lower() for slug in (public_identity_slugs or []) if slug]
    family = company_family(company_name)
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
        # Include all family names (e.g. ByteDance → also match TikTok)
        family_names = [name for name in family if name] if len(family) > 1 else []
        if family_names:
            company_filters.append(
                LinkedInGraphConnection.normalized_company_name.in_(family_names)
            )
        elif normalized_company_name:
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


async def get_followed_people_by_linkedin_slugs(
    db: AsyncSession,
    user_id: uuid.UUID,
    slugs: list[str],
) -> list[LinkedInGraphFollow]:
    normalized_slugs = sorted({slug.strip().lower() for slug in slugs if slug})
    if not normalized_slugs:
        return []

    result = await db.execute(
        select(LinkedInGraphFollow).where(
            LinkedInGraphFollow.user_id == user_id,
            LinkedInGraphFollow.entity_type == "person",
            LinkedInGraphFollow.linkedin_slug.in_(normalized_slugs),
        )
    )
    return list(result.scalars().all())


async def get_followed_companies_for_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> list[LinkedInGraphFollow]:
    normalized_company_name = normalize_company_name(company_name)
    trusted_slugs = [slug.strip().lower() for slug in (public_identity_slugs or []) if slug]
    family = company_family(company_name)
    query = select(LinkedInGraphFollow).where(
        LinkedInGraphFollow.user_id == user_id,
        LinkedInGraphFollow.entity_type == "company",
    )

    if is_ambiguous_company_name(company_name):
        if not trusted_slugs:
            return []
        query = query.where(LinkedInGraphFollow.linkedin_slug.in_(trusted_slugs))
    else:
        company_filters = []
        family_names = [name for name in family if name] if len(family) > 1 else []
        if family_names:
            company_filters.append(
                LinkedInGraphFollow.normalized_company_name.in_(family_names)
            )
        elif normalized_company_name:
            company_filters.append(
                LinkedInGraphFollow.normalized_company_name == normalized_company_name
            )
        if trusted_slugs:
            company_filters.append(LinkedInGraphFollow.linkedin_slug.in_(trusted_slugs))
        if not company_filters:
            return []
        query = query.where(or_(*company_filters))

    query = query.order_by(
        LinkedInGraphFollow.display_name.asc(),
        LinkedInGraphFollow.id.asc(),
    ).limit(10)
    result = await db.execute(query)
    return [
        follow
        for follow in result.scalars().all()
        if follow_matches_company(
            follow,
            company_name=company_name,
            public_identity_slugs=public_identity_slugs,
        )
    ]


def serialize_connection(connection: LinkedInGraphConnection | dict[str, Any]) -> dict[str, Any]:
    if isinstance(connection, dict):
        connection_id = connection.get("id")
        freshness = graph_freshness_metadata(connection.get("last_synced_at"))
        return {
            "id": str(connection_id) if connection_id is not None else "",
            "display_name": connection.get("display_name") or "",
            "headline": connection.get("headline"),
            "current_company_name": connection.get("current_company_name"),
            "linkedin_url": connection.get("linkedin_url"),
            "company_linkedin_url": connection.get("company_linkedin_url"),
            "source": connection.get("source") or "manual_import",
            "last_synced_at": connection.get("last_synced_at"),
            "freshness": freshness["freshness"],
            "days_since_sync": freshness["days_since_sync"],
            "refresh_recommended": freshness["refresh_recommended"],
            "stale": freshness["stale"],
            "caution": freshness["caution"],
        }

    freshness = graph_freshness_metadata(connection.last_synced_at)
    return {
        "id": str(connection.id),
        "display_name": connection.display_name,
        "headline": connection.headline,
        "current_company_name": connection.current_company_name,
        "linkedin_url": connection.linkedin_url,
        "company_linkedin_url": connection.company_linkedin_url,
        "source": connection.source,
        "last_synced_at": connection.last_synced_at,
        "freshness": freshness["freshness"],
        "days_since_sync": freshness["days_since_sync"],
        "refresh_recommended": freshness["refresh_recommended"],
        "stale": freshness["stale"],
        "caution": freshness["caution"],
    }


def serialize_follow(follow: LinkedInGraphFollow | dict[str, Any]) -> dict[str, Any]:
    if isinstance(follow, dict):
        follow_id = follow.get("id")
        freshness = graph_freshness_metadata(follow.get("last_synced_at"))
        return {
            "id": str(follow_id) if follow_id is not None else "",
            "entity_type": follow.get("entity_type") or "person",
            "display_name": follow.get("display_name") or "",
            "headline": follow.get("headline"),
            "current_company_name": follow.get("current_company_name"),
            "linkedin_url": follow.get("linkedin_url"),
            "company_linkedin_url": follow.get("company_linkedin_url"),
            "source": follow.get("source") or "manual_import",
            "last_synced_at": follow.get("last_synced_at"),
            "freshness": freshness["freshness"],
            "days_since_sync": freshness["days_since_sync"],
            "refresh_recommended": freshness["refresh_recommended"],
            "stale": freshness["stale"],
            "caution": freshness["caution"],
        }

    freshness = graph_freshness_metadata(follow.last_synced_at)
    return {
        "id": str(follow.id),
        "entity_type": follow.entity_type,
        "display_name": follow.display_name,
        "headline": follow.headline,
        "current_company_name": follow.current_company_name,
        "linkedin_url": follow.linkedin_url,
        "company_linkedin_url": follow.company_linkedin_url,
        "source": follow.source,
        "last_synced_at": follow.last_synced_at,
        "freshness": freshness["freshness"],
        "days_since_sync": freshness["days_since_sync"],
        "refresh_recommended": freshness["refresh_recommended"],
        "stale": freshness["stale"],
        "caution": freshness["caution"],
    }


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
    if company_slug and company_slug in trusted_slugs:
        return True

    # Parent/subsidiary family match: e.g. ByteDance ↔ TikTok
    if connection_company_name:
        family = company_family(company_name)
        if len(family) > 1 and connection_company_name in family:
            return True

    return False


def follow_matches_company(
    follow: LinkedInGraphFollow | dict[str, Any],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> bool:
    normalized_company_name = normalize_company_name(company_name)
    trusted_slugs = [slug.strip().lower() for slug in (public_identity_slugs or []) if slug]

    linkedin_slug = (
        follow.get("linkedin_slug")
        if isinstance(follow, dict)
        else follow.linkedin_slug
    )
    normalized_follow_company = (
        follow.get("normalized_company_name")
        if isinstance(follow, dict)
        else follow.normalized_company_name
    )

    if is_ambiguous_company_name(company_name):
        return bool(linkedin_slug and linkedin_slug in trusted_slugs)

    if normalized_follow_company and normalized_follow_company == normalized_company_name:
        return True
    if linkedin_slug and linkedin_slug in trusted_slugs:
        return True

    if normalized_follow_company:
        family = company_family(company_name)
        if len(family) > 1 and normalized_follow_company in family:
            return True

    return False


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


def _score_bridge_relevance(
    connection: LinkedInGraphConnection,
    *,
    job_title: str | None = None,
    department: str | None = None,
) -> tuple[int, str]:
    """Score how relevant a connection is as a bridge for a given job.

    Returns (score, display_name) — higher score = better bridge.
    Recruiter/talent connections rank highest because they can actually
    refer or forward internally.  Same-department peers rank next.
    """
    headline = (connection.headline or "").lower()
    score = 0

    # Recruiter/talent acquisition → best possible bridge
    recruiter_signals = (
        "recruiter", "recruiting", "talent acquisition",
        "talent scout", "sourcer", "campus recruiter",
        "university recruiter",
    )
    if any(signal in headline for signal in recruiter_signals):
        score += 50

    # HR / people ops → good bridge
    hr_signals = ("human resources", " hr ", "people ops", "people operations")
    if any(signal in headline for signal in hr_signals):
        score += 40

    # Same department signal from job title
    if job_title:
        job_lower = job_title.lower()
        # Engineering roles
        eng_signals = ("engineer", "developer", "swe", "sde", "devops", "infrastructure")
        if any(s in job_lower for s in eng_signals) and any(s in headline for s in eng_signals):
            score += 30
        # Product roles
        pm_signals = ("product manager", "product lead", "program manager")
        if any(s in job_lower for s in pm_signals) and any(s in headline for s in pm_signals):
            score += 30
        # Data/ML roles
        data_signals = ("data scien", "machine learning", " ml ", " ai ", "data engineer")
        if any(s in job_lower for s in data_signals) and any(s in headline for s in data_signals):
            score += 30
        # Design roles
        design_signals = ("designer", "design lead", "ux ", "ui ")
        if any(s in job_lower for s in design_signals) and any(s in headline for s in design_signals):
            score += 30

    # Department-level match if explicit department provided
    if department:
        dept_headline_map: dict[str, tuple[str, ...]] = {
            "engineering": ("engineer", "developer", "swe", "sde", "devops", "infrastructure"),
            "data_science": ("data scien", "machine learning", " ml ", " ai "),
            "product_management": ("product manager", "product lead"),
            "design": ("designer", "design", "ux"),
        }
        dept_signals = dept_headline_map.get(department, ())
        if any(s in headline for s in dept_signals):
            score += 15

    # Tie-break: prefer connections with LinkedIn URLs (more useful for intros)
    if connection.linkedin_url:
        score += 1

    return (score, connection.display_name or "")


def _select_best_bridge(
    connections: list[LinkedInGraphConnection],
    *,
    job_title: str | None = None,
    department: str | None = None,
) -> LinkedInGraphConnection | None:
    """Pick the most relevant bridge connection for a job."""
    if not connections:
        return None
    if len(connections) == 1:
        return connections[0]

    scored = [
        (
            _score_bridge_relevance(c, job_title=job_title, department=department),
            c,
        )
        for c in connections
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1]


def apply_warm_path_annotations(
    bucketed: dict[str, list[Any]],
    *,
    company_name: str,
    your_connections: list[LinkedInGraphConnection],
    direct_connections: list[LinkedInGraphConnection] | None = None,
    job_title: str | None = None,
    department: str | None = None,
) -> None:
    by_slug = {
        connection.linkedin_slug: connection
        for connection in (direct_connections or your_connections)
        if connection.linkedin_slug
    }
    bridge_connection = _select_best_bridge(
        your_connections, job_title=job_title, department=department,
    )
    bridge_company_name = bridge_connection.current_company_name if bridge_connection else company_name

    for people in bucketed.values():
        for person in people:
            setattr(person, "warm_path_type", None)
            setattr(person, "warm_path_reason", None)
            setattr(person, "warm_path_connection", None)
            setattr(person, "warm_path_freshness", None)
            setattr(person, "warm_path_days_since_sync", None)
            setattr(person, "warm_path_refresh_recommended", False)
            setattr(person, "warm_path_stale", False)
            setattr(person, "warm_path_caution", None)

            person_slug = _linkedin_slug_from_url(getattr(person, "linkedin_url", None))
            direct_connection = by_slug.get(person_slug) if person_slug else None
            if direct_connection is not None:
                freshness = graph_freshness_metadata(direct_connection.last_synced_at)
                setattr(person, "warm_path_type", "direct_connection")
                setattr(
                    person,
                    "warm_path_reason",
                    f"You are already connected to {direct_connection.display_name} on LinkedIn.",
                )
                setattr(person, "warm_path_connection", direct_connection)
                setattr(person, "warm_path_freshness", freshness["freshness"])
                setattr(person, "warm_path_days_since_sync", freshness["days_since_sync"])
                setattr(person, "warm_path_refresh_recommended", freshness["refresh_recommended"])
                setattr(person, "warm_path_stale", freshness["stale"])
                setattr(person, "warm_path_caution", freshness["caution"])
                continue

            if bridge_connection is None:
                continue

            freshness = graph_freshness_metadata(bridge_connection.last_synced_at)
            setattr(person, "warm_path_type", "same_company_bridge")
            setattr(
                person,
                "warm_path_reason",
                f"You already know {bridge_connection.display_name} at {bridge_company_name or company_name}.",
            )
            setattr(person, "warm_path_connection", bridge_connection)
            setattr(person, "warm_path_freshness", freshness["freshness"])
            setattr(person, "warm_path_days_since_sync", freshness["days_since_sync"])
            setattr(person, "warm_path_refresh_recommended", freshness["refresh_recommended"])
            setattr(person, "warm_path_stale", freshness["stale"])
            setattr(person, "warm_path_caution", freshness["caution"])


def apply_follow_signal_annotations(
    bucketed: dict[str, list[Any]],
    *,
    company_name: str,
    direct_follows: list[LinkedInGraphFollow] | None = None,
    company_follows: list[LinkedInGraphFollow] | None = None,
) -> None:
    by_slug = {
        follow.linkedin_slug: follow
        for follow in (direct_follows or [])
        if follow.linkedin_slug
    }
    company_follow = company_follows[0] if company_follows else None
    company_follow_name = company_follow.display_name if company_follow else company_name

    for people in bucketed.values():
        for person in people:
            setattr(person, "followed_person", False)
            setattr(person, "followed_company", False)
            setattr(person, "linkedin_signal_reason", None)
            setattr(person, "linkedin_signal_type", None)
            setattr(person, "linkedin_signal_display_name", None)
            setattr(person, "linkedin_signal_headline", None)
            setattr(person, "linkedin_signal_linkedin_url", None)
            setattr(person, "linkedin_signal_last_synced_at", None)
            setattr(person, "linkedin_signal_freshness", None)
            setattr(person, "linkedin_signal_days_since_sync", None)
            setattr(person, "linkedin_signal_refresh_recommended", False)
            setattr(person, "linkedin_signal_stale", False)
            setattr(person, "linkedin_signal_caution", None)

            person_slug = _linkedin_slug_from_url(getattr(person, "linkedin_url", None))
            direct_follow = by_slug.get(person_slug) if person_slug else None
            if direct_follow is not None:
                freshness = graph_freshness_metadata(direct_follow.last_synced_at)
                setattr(person, "followed_person", True)
                setattr(person, "linkedin_signal_reason", f"You follow {direct_follow.display_name} on LinkedIn.")
                setattr(person, "linkedin_signal_type", "followed_person")
                setattr(person, "linkedin_signal_display_name", direct_follow.display_name)
                setattr(person, "linkedin_signal_headline", direct_follow.headline)
                setattr(person, "linkedin_signal_linkedin_url", direct_follow.linkedin_url)
                setattr(person, "linkedin_signal_last_synced_at", direct_follow.last_synced_at)
                setattr(person, "linkedin_signal_freshness", freshness["freshness"])
                setattr(person, "linkedin_signal_days_since_sync", freshness["days_since_sync"])
                setattr(person, "linkedin_signal_refresh_recommended", freshness["refresh_recommended"])
                setattr(person, "linkedin_signal_stale", freshness["stale"])
                setattr(person, "linkedin_signal_caution", freshness["caution"])
                continue

            if company_follow is None:
                continue

            freshness = graph_freshness_metadata(company_follow.last_synced_at)
            setattr(person, "followed_company", True)
            setattr(person, "linkedin_signal_reason", f"You follow {company_follow_name} on LinkedIn.")
            setattr(person, "linkedin_signal_type", "followed_company")
            setattr(person, "linkedin_signal_display_name", company_follow.display_name)
            setattr(person, "linkedin_signal_headline", company_follow.headline)
            setattr(person, "linkedin_signal_linkedin_url", company_follow.linkedin_url)
            setattr(person, "linkedin_signal_last_synced_at", company_follow.last_synced_at)
            setattr(person, "linkedin_signal_freshness", freshness["freshness"])
            setattr(person, "linkedin_signal_days_since_sync", freshness["days_since_sync"])
            setattr(person, "linkedin_signal_refresh_recommended", freshness["refresh_recommended"])
            setattr(person, "linkedin_signal_stale", freshness["stale"])
            setattr(person, "linkedin_signal_caution", freshness["caution"])


async def resolve_warm_path_for_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    person: Any,
    *,
    job_title: str | None = None,
    department: str | None = None,
) -> dict[str, Any] | None:
    """Resolve warm-path context for a single person (for drafting).

    Returns a dict with ``type``, ``reason``, and connection summary fields,
    or ``None`` if the user has no safe warm path to this person. Mirrors
    the ranking rules in ``apply_warm_path_annotations`` but for one target.
    """
    company = getattr(person, "company", None)
    company_name = getattr(company, "name", None) if company else None
    if not company_name:
        return None

    public_identity_slugs = (
        getattr(company, "public_identity_slugs", None) if company else None
    ) or []

    connections = await get_connections_for_company(
        db,
        user_id,
        company_name=company_name,
        public_identity_slugs=public_identity_slugs,
    )
    if not connections:
        return None

    person_slug = _linkedin_slug_from_url(getattr(person, "linkedin_url", None))
    if person_slug:
        for connection in connections:
            if connection.linkedin_slug == person_slug:
                freshness = graph_freshness_metadata(connection.last_synced_at)
                return {
                    "type": "direct_connection",
                    "reason": (
                        f"You are already directly connected to "
                        f"{connection.display_name} on LinkedIn."
                    ),
                    "connection_name": connection.display_name,
                    "connection_headline": connection.headline,
                    "connection_linkedin_url": connection.linkedin_url,
                    "freshness": freshness["freshness"],
                    "days_since_sync": freshness["days_since_sync"],
                    "refresh_recommended": freshness["refresh_recommended"],
                    "stale": freshness["stale"],
                    "caution": freshness["caution"],
                }

    bridge = _select_best_bridge(
        connections, job_title=job_title, department=department
    )
    if bridge is None:
        return None

    bridge_company = bridge.current_company_name or company_name
    freshness = graph_freshness_metadata(bridge.last_synced_at)
    return {
        "type": "same_company_bridge",
        "reason": (
            f"You already know {bridge.display_name} at {bridge_company}, "
            f"who may be able to introduce you."
        ),
        "connection_name": bridge.display_name,
        "connection_headline": bridge.headline,
        "connection_linkedin_url": bridge.linkedin_url,
        "freshness": freshness["freshness"],
        "days_since_sync": freshness["days_since_sync"],
        "refresh_recommended": freshness["refresh_recommended"],
        "stale": freshness["stale"],
        "caution": freshness["caution"],
    }


async def resolve_linkedin_signal_for_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    person: Any,
) -> dict[str, Any] | None:
    company = getattr(person, "company", None)
    company_name = getattr(company, "name", None) if company else None
    public_identity_slugs = (
        getattr(company, "public_identity_slugs", None) if company else None
    ) or []

    person_slug = _linkedin_slug_from_url(getattr(person, "linkedin_url", None))
    if person_slug:
        follows = await get_followed_people_by_linkedin_slugs(db, user_id, [person_slug])
        if follows:
            follow = follows[0]
            freshness = graph_freshness_metadata(follow.last_synced_at)
            return {
                "type": "followed_person",
                "reason": f"You follow {follow.display_name} on LinkedIn.",
                "display_name": follow.display_name,
                "headline": follow.headline,
                "linkedin_url": follow.linkedin_url,
                "freshness": freshness["freshness"],
                "days_since_sync": freshness["days_since_sync"],
                "refresh_recommended": freshness["refresh_recommended"],
                "stale": freshness["stale"],
                "caution": freshness["caution"],
            }

    if not company_name:
        return None

    company_follows = await get_followed_companies_for_company(
        db,
        user_id,
        company_name=company_name,
        public_identity_slugs=public_identity_slugs,
    )
    if not company_follows:
        return None

    follow = company_follows[0]
    freshness = graph_freshness_metadata(follow.last_synced_at)
    return {
        "type": "followed_company",
        "reason": f"You follow {follow.display_name} on LinkedIn.",
        "display_name": follow.display_name,
        "headline": follow.headline,
        "linkedin_url": follow.linkedin_url,
        "freshness": freshness["freshness"],
        "days_since_sync": freshness["days_since_sync"],
        "refresh_recommended": freshness["refresh_recommended"],
        "stale": freshness["stale"],
        "caution": freshness["caution"],
    }
