"""LinkedIn graph row upserts, lookups, and serialization."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.linkedin_graph import (
    LinkedInGraphConnection,
    LinkedInGraphFollow,
)
from app.models.settings import UserSettings
from app.utils.company_identity import (
    company_family,
    is_ambiguous_company_name,
    normalize_company_name,
)
from app.services.linkedin_graph.matching import connection_matches_company, follow_matches_company
from app.services.linkedin_graph.parsing import _clean_text, dedupe_connection_candidates, dedupe_follow_candidates

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
