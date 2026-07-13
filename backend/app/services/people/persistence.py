"""Company/person persistence, page captures, and saved-people queries."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import apollo_client
from app.models.company import Company
from app.models.person import Person
from app.services import linkedin_graph_service
from app.utils.company_identity import (
    build_public_identity_hints,
    canonical_company_display_name,
    is_ambiguous_company_name,
    normalize_company_name,
    should_trust_company_enrichment,
)
from app.utils.linkedin import normalize_linkedin_url

from app.services.people.buckets import _apply_match_metadata, _bucketed_linkedin_slugs
from app.services.people.classify import _classify_person
from app.services.people.titles import _title_is_weak
logger = logging.getLogger(__name__)


async def get_or_create_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
    *,
    ats_slug: str | None = None,
    careers_url: str | None = None,
) -> Company:
    """Find existing company or create plus enrich a new one."""
    requested_name = canonical_company_display_name(company_name)
    normalized_name = normalize_company_name(requested_name)
    result = await db.execute(
        select(Company).where(
            Company.user_id == user_id,
            Company.normalized_name == normalized_name,
        )
    )
    company = result.scalars().first()
    company_data = None
    if not company or not getattr(company, "public_identity_slugs", None):
        company_data = await apollo_client.search_company(requested_name)

    if company:
        if len(requested_name) < len(company.name or ""):
            company.name = requested_name
        if not company.domain_trusted and is_ambiguous_company_name(requested_name):
            company.domain = None
            company.domain_trusted = False
            company.email_pattern = None
            company.email_pattern_confidence = None
        identity_bundle = build_public_identity_hints(
            requested_name,
            existing_slugs=getattr(company, "public_identity_slugs", None),
            existing_hints=getattr(company, "identity_hints", None),
            ats_slug=ats_slug,
            domain=company.domain,
            careers_url=careers_url
            or getattr(company, "careers_url", None)
            or (company_data or {}).get("careers_url"),
            linkedin_company_url=(company_data or {}).get("linkedin_url"),
        )
        company.public_identity_slugs = identity_bundle.slugs
        company.identity_hints = identity_bundle.hints
        if careers_url:
            company.careers_url = careers_url
        elif company_data and not getattr(company, "careers_url", None):
            company.careers_url = company_data.get("careers_url")
        return company

    trusted_domain = None
    use_apollo_enrichment = False
    if company_data:
        use_apollo_enrichment = should_trust_company_enrichment(
            requested_name,
            resolved_name=company_data.get("name"),
            domain=company_data.get("domain"),
        )
        if use_apollo_enrichment:
            trusted_domain = company_data.get("domain")
    identity_bundle = build_public_identity_hints(
        requested_name,
        ats_slug=ats_slug,
        domain=trusted_domain or (company_data or {}).get("domain"),
        careers_url=careers_url or (company_data or {}).get("careers_url"),
        linkedin_company_url=(company_data or {}).get("linkedin_url"),
    )

    company = Company(
        user_id=user_id,
        name=requested_name,
        normalized_name=normalized_name,
        domain=trusted_domain,
        domain_trusted=bool(trusted_domain),
        public_identity_slugs=identity_bundle.slugs,
        identity_hints=identity_bundle.hints,
        size=str(company_data.get("size", "")) if company_data and use_apollo_enrichment else None,
        industry=company_data.get("industry") if company_data and use_apollo_enrichment else None,
        description=company_data.get("description") if company_data and use_apollo_enrichment else None,
        careers_url=careers_url or (company_data.get("careers_url") if company_data else None),
        enriched_at=datetime.now(timezone.utc) if company_data and use_apollo_enrichment else None,
    )
    db.add(company)
    try:
        # SAVEPOINT so a concurrent get_or_create_company for the same
        # (user_id, normalized_name) — pre-warm / snapshot refresh / live search
        # can run at once — doesn't poison the outer transaction. After a
        # UniqueViolationError asyncpg marks the transaction unusable, so
        # ROLLBACK TO SAVEPOINT is what lets the request continue.
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        # Lost the race: another transaction inserted this company first.
        # Drop our pending row and use the existing one.
        if company in db:
            db.expunge(company)
        existing = await db.execute(
            select(Company).where(
                Company.user_id == user_id,
                Company.normalized_name == normalized_name,
            )
        )
        company = existing.scalars().first()
        if company is None:
            raise  # a different integrity error — don't swallow it
    return company


async def _store_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    company: Company | None,
    data: dict,
    person_type: str,
) -> Person:
    """Create or update a Person record from API data."""
    from app.utils.linkedin import normalize_linkedin_url

    raw_linkedin = data.get("linkedin_url", "")
    linkedin = normalize_linkedin_url(raw_linkedin) or raw_linkedin or ""
    apollo_id = data.get("apollo_id", "")
    company_id = company.id if company else None
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    public_url = profile_data.get("public_url") if isinstance(profile_data.get("public_url"), str) else ""

    if public_url:
        result = await db.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.profile_data["public_url"].astext == public_url,
            )
        )
        existing = result.scalars().first()
        if existing:
            if apollo_id and not existing.apollo_id:
                existing.apollo_id = apollo_id
            if (
                data.get("title")
                and (
                    not existing.title
                    or (_title_is_weak(existing.title, company.name if company else "") and not _title_is_weak(data.get("title"), company.name if company else ""))
                )
            ):
                existing.title = data.get("title")
            if not existing.full_name and data.get("full_name"):
                existing.full_name = data.get("full_name")
            if linkedin and not existing.linkedin_url:
                existing.linkedin_url = linkedin
            if company_id and existing.company_id != company_id:
                existing.company_id = company_id
            if company:
                existing.company = company
            merged_profile_data = existing.profile_data if isinstance(existing.profile_data, dict) else {}
            merged_profile_data.update(profile_data)
            existing.profile_data = merged_profile_data
            return existing

    if linkedin:
        result = await db.execute(
            select(Person).where(Person.user_id == user_id, Person.linkedin_url == linkedin)
        )
        existing = result.scalars().first()
        if existing:
            if apollo_id and not existing.apollo_id:
                existing.apollo_id = apollo_id
            if (
                data.get("title")
                and (
                    not existing.title
                    or (_title_is_weak(existing.title, company.name if company else "") and not _title_is_weak(data.get("title"), company.name if company else ""))
                )
            ):
                existing.title = data.get("title")
            if not existing.full_name and data.get("full_name"):
                existing.full_name = data.get("full_name")
            if company_id and existing.company_id != company_id:
                existing.company_id = company_id
            if company:
                existing.company = company
            if profile_data:
                merged_profile_data = existing.profile_data if isinstance(existing.profile_data, dict) else {}
                merged_profile_data.update(profile_data)
                existing.profile_data = merged_profile_data
            return existing

    if not linkedin and apollo_id:
        result = await db.execute(
            select(Person).where(Person.user_id == user_id, Person.apollo_id == apollo_id)
        )
        existing = result.scalars().first()
        if existing:
            if company_id and existing.company_id != company_id:
                existing.company_id = company_id
            if company:
                existing.company = company
            return existing

    # Name + company dedup (case-insensitive) — catches cross-source duplicates
    if not linkedin and not apollo_id and data.get("full_name") and company_id:
        normalized_name = data["full_name"].strip().lower()
        result = await db.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.company_id == company_id,
                func.lower(func.trim(Person.full_name)) == normalized_name,
            )
        )
        existing = result.scalars().first()
        if existing:
            if (
                data.get("title")
                and (
                    not existing.title
                    or (_title_is_weak(existing.title, company.name if company else "") and not _title_is_weak(data.get("title"), company.name if company else ""))
                )
            ):
                existing.title = data.get("title")
            if linkedin and not existing.linkedin_url:
                existing.linkedin_url = linkedin
            if company:
                existing.company = company
            if profile_data:
                merged_profile_data = existing.profile_data if isinstance(existing.profile_data, dict) else {}
                merged_profile_data.update(profile_data)
                existing.profile_data = merged_profile_data
            return existing

    person = Person(
        user_id=user_id,
        company_id=company_id,
        full_name=data.get("full_name"),
        title=data.get("title"),
        department=data.get("department"),
        seniority=data.get("seniority"),
        linkedin_url=linkedin or None,
        github_url=data.get("github_url"),
        work_email=data.get("work_email"),
        # Prefer an explicit email-specific source; fall back to the discovery
        # source only when the email came directly from it (e.g. Apollo). The
        # email finder service overwrites this with its own source later (L13).
        email_source=(
            data.get("email_source") or data.get("source")
            if data.get("work_email")
            else None
        ),
        email_verified=data.get("email_verified", False),
        person_type=person_type,
        profile_data=profile_data or {k: v for k, v in data.items() if k != "source"},
        github_data=data.get("github_data"),
        source=data.get("source", "unknown"),
        apollo_id=apollo_id or None,
        relevance_score=data.get("relevance_score"),
    )
    if company:
        person.company = company
    db.add(person)
    return person


def _normalize_linkedin_page_capture(payload: dict[str, Any]) -> dict[str, Any]:
    normalized_url = normalize_linkedin_url(payload.get("linkedin_url"))
    capture: dict[str, Any] = {
        "source": "local_linkedin_page",
        "linkedin_url": normalized_url,
        "linkedin_slug": normalized_url.rstrip("/").rsplit("/", 1)[-1] if normalized_url else None,
        "visible_name": (payload.get("visible_name") or "").strip() or None,
        "headline": (payload.get("headline") or "").strip() or None,
        "location": (payload.get("location") or "").strip() or None,
        "current_role_title": (payload.get("current_role_title") or "").strip() or None,
        "current_company_label": (payload.get("current_company_label") or "").strip() or None,
        "about_snippet": (payload.get("about_snippet") or "").strip() or None,
        "recent_experience_snippet": (payload.get("recent_experience_snippet") or "").strip() or None,
        "captured_at": (
            payload.get("captured_at").astimezone(timezone.utc).isoformat()
            if isinstance(payload.get("captured_at"), datetime)
            else datetime.now(timezone.utc).isoformat()
        ),
    }
    return {key: value for key, value in capture.items() if value is not None}


async def persist_linkedin_page_capture(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    payload: dict[str, Any],
) -> Person:
    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if person is None:
        raise ValueError("Person not found.")

    profile_data = dict(person.profile_data or {}) if isinstance(person.profile_data, dict) else {}
    profile_data["linkedin_live"] = _normalize_linkedin_page_capture(payload)
    person.profile_data = profile_data

    normalized_url = normalize_linkedin_url(payload.get("linkedin_url"))
    if normalized_url and not person.linkedin_url:
        person.linkedin_url = normalized_url

    await db.commit()
    await db.refresh(person)
    return person


async def capture_linkedin_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: dict[str, Any],
) -> Person:
    """Save a contact from a LinkedIn profile the user is viewing (Workstream E).

    Ambient "Save to NexusReach" from the companion: read-only capture of the
    top-card fields the user personally has on screen. Upserts a CRM ``Person``
    by ``(user_id, linkedin_url)`` and links a ``Company`` when a current
    employer is visible. Because the user viewed the live profile, the current
    company is treated as verified evidence (like a hiring-team capture), never
    a SERP guess. Email trust is untouched — that stays in its own waterfall.

    This creates a CRM row on explicit user action; it never writes
    ``linkedin_graph_connections`` and never seeds the global known-people
    cache (that is for discovery corroboration, not a user's ad-hoc save).
    """
    normalized = normalize_linkedin_url(payload.get("linkedin_url"))
    if not normalized:
        raise ValueError("A valid LinkedIn profile URL is required.")

    capture = _normalize_linkedin_page_capture({**payload, "linkedin_url": normalized})
    capture["source"] = "companion_capture"

    full_name = (payload.get("visible_name") or "").strip() or None
    title = (
        (payload.get("current_role_title") or "").strip()
        or (payload.get("headline") or "").strip()
        or None
    )
    company_label = (payload.get("current_company_label") or "").strip() or None

    company: Company | None = None
    if company_label:
        company = await get_or_create_company(db, user_id, company_label)

    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.user_id == user_id, Person.linkedin_url == normalized)
    )
    person = result.scalar_one_or_none()

    if person is None:
        person = Person(
            user_id=user_id,
            full_name=full_name,
            title=title,
            linkedin_url=normalized,
            person_type=_classify_person(title or ""),
            source="companion_capture",
            profile_data={"linkedin_live": capture},
        )
        db.add(person)
    else:
        # Fill blanks; never clobber an existing (possibly stronger) value.
        if full_name and not person.full_name:
            person.full_name = full_name
        if title and not person.title:
            person.title = title
        profile_data = dict(person.profile_data) if isinstance(person.profile_data, dict) else {}
        profile_data["linkedin_live"] = capture
        person.profile_data = profile_data

    if company is not None:
        person.company = company
        # The user personally viewed the live profile stating this employer:
        # strong direct evidence of current employment.
        person.current_company_verified = True
        person.current_company_verification_status = "verified"
        person.current_company_verification_source = "companion_capture"
        person.current_company_verified_at = datetime.now(timezone.utc)
        person.current_company_verification_evidence = (
            "Saved from the member's LinkedIn profile"
        )

    await db.commit()
    await db.refresh(person)
    return person


async def get_saved_people(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Person], int]:
    """Get saved people for a user with optional filtering and pagination.

    Returns ``(people, total_count)``.
    """
    from app.utils.pagination import paginate

    query = select(Person).options(selectinload(Person.company)).where(Person.user_id == user_id)
    if company_id:
        query = query.where(Person.company_id == company_id)
    query = query.order_by(Person.created_at.desc())

    people, total = await paginate(db, query, limit=limit, offset=offset)
    for person in people:
        company_name = person.company.name if person.company else None
        data = {
            "title": person.title or "",
            "snippet": (person.profile_data or {}).get("snippet", "") if isinstance(person.profile_data, dict) else "",
            "source": person.source or "",
            "profile_data": person.profile_data or {},
        }
        _apply_match_metadata(
            person,
            data,
            person.person_type or _classify_person(person.title or "", source=person.source or ""),
            context=None,
            company_name=company_name,
        )

    direct_follows = await linkedin_graph_service.get_followed_people_by_linkedin_slugs(
        db,
        user_id,
        _bucketed_linkedin_slugs({"saved": people}),
    )
    grouped_people: dict[str, list[Person]] = {}
    for person in people:
        company_name = person.company.name if person.company else ""
        grouped_people.setdefault(company_name, []).append(person)

    for company_name, grouped in grouped_people.items():
        company_follows = []
        if company_name:
            public_identity_slugs = (
                grouped[0].company.public_identity_slugs
                if grouped and grouped[0].company and grouped[0].company.public_identity_slugs
                else []
            )
            company_follows = await linkedin_graph_service.get_followed_companies_for_company(
                db,
                user_id,
                company_name=company_name,
                public_identity_slugs=public_identity_slugs,
            )
        linkedin_graph_service.apply_follow_signal_annotations(
            {"saved": grouped},
            company_name=company_name or "this company",
            direct_follows=direct_follows,
            company_follows=company_follows,
        )
    return people, total


async def get_search_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 20,
) -> list:
    """Return recent search logs for a user."""
    from app.models.search_log import SearchLog

    result = await db.execute(
        select(SearchLog)
        .where(SearchLog.user_id == user_id)
        .order_by(SearchLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
