"""Warm-path and follow-signal resolution from the imported graph."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.linkedin_graph import (
    LinkedInGraphConnection,
    LinkedInGraphFollow,
)
from app.services.linkedin_graph.parsing import _linkedin_slug_from_url
from app.services.linkedin_graph.store import graph_freshness_metadata, get_connections_for_company, get_followed_companies_for_company, get_followed_people_by_linkedin_slugs

logger = logging.getLogger(__name__)


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
