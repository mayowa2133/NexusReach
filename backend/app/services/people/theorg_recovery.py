"""The Org slug resolution and title recovery for people discovery."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import theorg_client
from app.config import settings
from app.models.company import Company
from app.models.person import Person
from app.utils.company_identity import (
    effective_public_identity_slugs,
    extract_public_identity_hints,
    is_ambiguous_company_name,
    is_compatible_public_identity_slug,
    matches_public_company_identity,
)

from app.services.people.identity import _normalize_identity, _public_profile_url
from app.services.people.titles import _recover_title_from_snippet
from app.services.people.titles import _title_is_weak
logger = logging.getLogger(__name__)


def _candidate_public_identity_slug(data: dict) -> str:
    profile_data = data.get("profile_data") or {}
    slug = profile_data.get("public_identity_slug")
    if isinstance(slug, str) and slug.strip():
        return slug.strip().lower()
    public_url = _public_profile_url(data)
    hints = extract_public_identity_hints(public_url)
    resolved = hints.get("company_slug")
    return resolved.strip().lower() if isinstance(resolved, str) and resolved.strip() else ""


def _merge_company_public_identity_slugs(
    company: Company,
    company_name: str,
    slugs: list[str],
    *,
    preferred_slug: str | None = None,
    preferred_status: str | None = None,
) -> None:
    merged = {slug for slug in (company.public_identity_slugs or []) if slug}
    accepted_slugs: set[str] = set()
    for slug in slugs:
        clean = (slug or "").strip().lower()
        effective_existing = effective_public_identity_slugs(
            company_name,
            list(merged),
            identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
        )
        if clean and (
            is_compatible_public_identity_slug(company_name, clean)
            or matches_public_company_identity(
                f"https://theorg.com/org/{clean}",
                company_name,
                effective_existing,
            )
        ):
            merged.add(clean)
            accepted_slugs.add(clean)
    hints = company.identity_hints if isinstance(company.identity_hints, dict) else {}
    company.public_identity_slugs = effective_public_identity_slugs(
        company_name,
        sorted(merged),
        identity_hints=hints,
    )

    theorg_hints = hints.setdefault("theorg", {})
    clean_preferred = (preferred_slug or "").strip().lower()
    preferred_allowed = bool(clean_preferred) and (
        clean_preferred in accepted_slugs
        or clean_preferred in set(company.public_identity_slugs or [])
        or is_compatible_public_identity_slug(company_name, clean_preferred)
        or matches_public_company_identity(
            f"https://theorg.com/org/{clean_preferred}",
            company_name,
            company.public_identity_slugs,
        )
    )
    if clean_preferred and preferred_status == "validated" and preferred_allowed:
        theorg_hints["preferred_org_slug"] = clean_preferred
    if clean_preferred and preferred_status and preferred_allowed:
        slug_status = theorg_hints.setdefault("slug_status", {})
        slug_status[clean_preferred] = preferred_status
    company.identity_hints = hints


def _title_recovery_metadata(
    data: dict,
    *,
    source: str | None = None,
    confidence: int | None = None,
    resolved_slug: str | None = None,
    slug_status: str | None = None,
) -> dict:
    profile_data = dict(data.get("profile_data") or {})
    if source:
        profile_data["title_recovery_source"] = source
    if confidence is not None:
        profile_data["title_recovery_confidence"] = confidence
    if resolved_slug:
        profile_data["public_identity_slug"] = resolved_slug
        profile_data["public_identity_slug_resolution"] = resolved_slug
    if slug_status:
        profile_data["public_identity_slug_status"] = slug_status
    return profile_data


async def _recover_title_from_theorg_page(
    data: dict,
    *,
    company: Company,
    company_name: str,
) -> tuple[str, int, str, str] | None:
    public_url = _public_profile_url(data)
    if not public_url:
        return None

    trusted_slugs = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    )
    if not matches_public_company_identity(public_url, company_name, trusted_slugs):
        return None

    page = await theorg_client.fetch_page(
        public_url, timeout_seconds=settings.theorg_timeout_seconds
    )
    if not page:
        return None

    hints = extract_public_identity_hints(public_url)
    page_type = hints.get("page_type")
    resolved_slug = hints.get("company_slug")
    if page_type == "org_chart_person":
        parsed = theorg_client.parse_person_page(page or {})
        person = (parsed or {}).get("person")
        recovered = (person or {}).get("title")
        if recovered and not _title_is_weak(recovered, company_name):
            return recovered, 95, (parsed or {}).get("org_slug") or resolved_slug or "", "validated"
    if page_type == "team":
        parsed = theorg_client.parse_team_page(page or {})
        people = (parsed or {}).get("people", [])
        for person in people:
            if _normalize_identity(person.get("full_name")) != _normalize_identity(data.get("full_name")):
                continue
            recovered = person.get("title")
            if recovered and not _title_is_weak(recovered, company_name):
                return recovered, 88, (parsed or {}).get("org_slug") or resolved_slug or "", "validated"
    return None


async def _recover_candidate_titles(
    candidates: list[dict],
    *,
    company: Company,
    company_name: str,
) -> list[dict]:
    recovered_candidates: list[dict] = []
    for raw in candidates:
        data = dict(raw)
        title = data.get("title", "") or ""
        resolved_slug = _candidate_public_identity_slug(data)
        if resolved_slug:
            _merge_company_public_identity_slugs(
                company,
                company_name,
                [resolved_slug],
                preferred_slug=resolved_slug if not is_ambiguous_company_name(company_name) else None,
                preferred_status="candidate",
            )
            data["profile_data"] = _title_recovery_metadata(
                data,
                resolved_slug=resolved_slug,
                slug_status="candidate",
            )

        if _title_is_weak(title, company_name):
            recovered = _recover_title_from_snippet(data, company_name=company_name)
            if recovered:
                recovered_title, confidence = recovered
                data["title"] = recovered_title
                data["profile_data"] = _title_recovery_metadata(
                    data,
                    source="snippet",
                    confidence=confidence,
                    resolved_slug=resolved_slug or None,
                    slug_status="candidate" if resolved_slug else None,
                )
            else:
                recovered_from_theorg = await _recover_title_from_theorg_page(
                    data,
                    company=company,
                    company_name=company_name,
                )
                if recovered_from_theorg:
                    recovered_title, confidence, theorg_slug, slug_status = recovered_from_theorg
                    data["title"] = recovered_title
                    _merge_company_public_identity_slugs(
                        company,
                        company_name,
                        [theorg_slug] if theorg_slug else [],
                        preferred_slug=theorg_slug or None,
                        preferred_status=slug_status,
                    )
                    data["profile_data"] = _title_recovery_metadata(
                        data,
                        source="theorg",
                        confidence=confidence,
                        resolved_slug=theorg_slug or resolved_slug or None,
                        slug_status=slug_status,
                    )

        data["_weak_title"] = _title_is_weak(data.get("title"), company_name)
        recovered_candidates.append(data)

    return recovered_candidates


async def _saved_theorg_slug_candidates(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company: Company,
) -> list[str]:
    if not company.id:
        return []
    result = await db.execute(
        select(Person).where(
            Person.user_id == user_id,
            Person.company_id == company.id,
        )
    )
    trusted_slugs = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    )
    candidates: list[str] = []
    for person in result.scalars().all():
        profile_data = person.profile_data if isinstance(person.profile_data, dict) else {}
        public_url = profile_data.get("public_url") if isinstance(profile_data.get("public_url"), str) else ""
        slug = ""
        if public_url:
            slug = (extract_public_identity_hints(public_url).get("company_slug") or "").strip().lower()
        if not slug:
            raw_slug = profile_data.get("public_identity_slug")
            if isinstance(raw_slug, str):
                slug = raw_slug.strip().lower()
        if slug and matches_public_company_identity(
            f"https://theorg.com/org/{slug}",
            company.name,
            trusted_slugs,
        ):
            candidates.append(slug)
    return list(dict.fromkeys(candidates))


def _candidate_theorg_slug_candidates(
    *groups: list[dict],
    company_name: str,
    trusted_slugs: list[str] | None = None,
) -> list[str]:
    slugs: list[str] = []
    for group in groups:
        for candidate in group:
            slug = _candidate_public_identity_slug(candidate)
            if slug and matches_public_company_identity(
                f"https://theorg.com/org/{slug}",
                company_name,
                trusted_slugs,
            ):
                slugs.append(slug)
    return list(dict.fromkeys(slugs))
