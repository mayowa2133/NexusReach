"""Global known people cache — shared discovery intelligence across all users.

This service manages a cross-user cache of publicly discovered people.
When any user's people search discovers contacts through public sources
(Apollo, SearXNG, The Org, GitHub, etc.), those contacts are written
to the global cache.  Subsequent searches by other users check the cache
first for instant results.

PRIVACY BOUNDARY: Only candidates discovered from public sources are
eligible for the global cache.  User-imported LinkedIn connection data
(source = "local_sync" or "manual_import") is NEVER written here.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.known_person import KnownPerson, KnownPersonCompany

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source eligibility — the privacy gate
# ---------------------------------------------------------------------------

GLOBAL_CACHE_ELIGIBLE_SOURCES = frozenset({
    "apollo",
    "proxycurl",
    "brave_hiring_team",
    "serper_hiring_team",
    "searxng_hiring_team",
    "theorg_traversal",
    "brave_search",
    "serper_search",
    "searxng_search",
    "google_cse",
    "brave_public_web",
    "serper_public_web",
    "searxng_public_web",
    "tavily_public_web",
    "github",
    "linkedin_backfill",
})

GLOBAL_CACHE_BLOCKED_SOURCES = frozenset({
    "local_sync",
    "manual_import",
    "manual",
})


def is_cache_eligible(candidate: dict) -> bool:
    """Return True only if the candidate's source is in the public allowlist."""
    source = (candidate.get("source") or "").strip().lower()
    if source in GLOBAL_CACHE_BLOCKED_SOURCES:
        return False
    return source in GLOBAL_CACHE_ELIGIBLE_SOURCES


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    """Lowercase, collapse whitespace, strip."""
    return _WHITESPACE_RE.sub(" ", name.strip().lower())


def _normalize_company(name: str) -> str:
    return _normalize_name(name)


# ---------------------------------------------------------------------------
# Lookup — read from cache
# ---------------------------------------------------------------------------


async def lookup_known_people(
    db: AsyncSession,
    *,
    company_name: str,
    limit: int = 25,
    max_staleness_days: int = 90,
) -> list[dict]:
    """Look up known people for a company from the global cache.

    Returns candidate dicts in a shape compatible with the people discovery
    pipeline so they can be mixed with live search results.

    Only returns records that are not expired (within *max_staleness_days*).
    """
    normalized = _normalize_company(company_name)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_staleness_days)

    stmt = (
        select(KnownPerson, KnownPersonCompany)
        .join(
            KnownPersonCompany,
            KnownPersonCompany.known_person_id == KnownPerson.id,
        )
        .where(
            KnownPersonCompany.normalized_company_name == normalized,
            KnownPersonCompany.is_current == True,  # noqa: E712
            KnownPerson.verification_status != "expired",
            KnownPerson.created_at >= cutoff,
        )
        .order_by(KnownPerson.discovery_count.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    candidates: list[dict] = []
    for kp, kpc in rows:
        candidates.append(_to_candidate_dict(kp, kpc))

    return candidates


async def get_known_people_count(
    db: AsyncSession,
    *,
    company_name: str,
) -> int:
    """Count known people at a company (for UI badges)."""
    normalized = _normalize_company(company_name)
    stmt = (
        select(func.count())
        .select_from(KnownPersonCompany)
        .join(KnownPerson, KnownPerson.id == KnownPersonCompany.known_person_id)
        .where(
            KnownPersonCompany.normalized_company_name == normalized,
            KnownPersonCompany.is_current == True,  # noqa: E712
            KnownPerson.verification_status != "expired",
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Write-through — populate cache after discovery
# ---------------------------------------------------------------------------


async def write_candidates_to_cache(
    db: AsyncSession,
    candidates: list[dict],
    *,
    company_name: str,
    company_domain: str | None = None,
) -> int:
    """Write publicly-discovered candidates to the global cache.

    Filters by source eligibility, deduplicates against existing records
    by linkedin_url / apollo_id / (normalized_name + company), and merges
    new data.  Returns count of new + updated records.
    """
    eligible = [c for c in candidates if is_cache_eligible(c)]
    if not eligible:
        return 0

    normalized_company = _normalize_company(company_name)
    now = datetime.now(timezone.utc)
    written = 0

    for candidate in eligible:
        full_name = (candidate.get("full_name") or "").strip()
        if not full_name:
            continue

        normalized = _normalize_name(full_name)
        linkedin_url = (candidate.get("linkedin_url") or "").strip() or None
        apollo_id = (candidate.get("apollo_id") or "").strip() or None
        source = (candidate.get("source") or "").strip()

        # Try to find existing record
        existing = await _find_existing(db, linkedin_url=linkedin_url, apollo_id=apollo_id, normalized_name=normalized)

        if existing:
            # Merge / update
            existing.discovery_count = (existing.discovery_count or 1) + 1
            existing.last_discovered_at = now

            # Update title if newer
            new_title = (candidate.get("title") or "").strip()
            if new_title and new_title != existing.title:
                existing.title = new_title

            # Add source
            if source and source not in (existing.all_sources or []):
                existing.all_sources = list(existing.all_sources or []) + [source]

            # Update profile data
            if candidate.get("profile_data"):
                existing.profile_data = {
                    **(existing.profile_data or {}),
                    **candidate["profile_data"],
                }

            # Ensure company association exists
            await _ensure_company_association(
                db, existing.id, company_name, normalized_company,
                company_domain=company_domain,
                title_at_company=candidate.get("title"),
            )
            written += 1
        else:
            # Create new
            kp = KnownPerson(
                full_name=full_name,
                normalized_name=normalized,
                title=(candidate.get("title") or "").strip() or None,
                department=(candidate.get("department") or "").strip() or None,
                seniority=(candidate.get("seniority") or "").strip() or None,
                linkedin_url=linkedin_url,
                github_url=(candidate.get("github_url") or "").strip() or None,
                work_email=(candidate.get("work_email") or "").strip() or None,
                apollo_id=apollo_id,
                profile_data=candidate.get("profile_data"),
                github_data=candidate.get("github_data"),
                primary_source=source,
                all_sources=[source] if source else [],
                discovery_count=1,
                last_discovered_at=now,
                last_verified_at=now,
                verification_status="fresh",
            )
            db.add(kp)
            await db.flush()  # Get the ID

            # Company association
            kpc = KnownPersonCompany(
                known_person_id=kp.id,
                company_name=company_name,
                normalized_company_name=normalized_company,
                company_domain=company_domain,
                title_at_company=candidate.get("title"),
                is_current=True,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(kpc)
            written += 1

    if written > 0:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Failed to write %d candidates to known people cache", written)
            return 0

    logger.info(
        "Known people cache: wrote %d/%d eligible candidates for %s",
        written, len(eligible), company_name,
    )
    return written


# ---------------------------------------------------------------------------
# Staleness management
# ---------------------------------------------------------------------------


async def mark_stale_records(
    db: AsyncSession,
    *,
    staleness_days: int = 14,
    expiry_days: int = 90,
) -> dict:
    """Mark records as stale or expired based on age."""
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=staleness_days)
    expiry_cutoff = now - timedelta(days=expiry_days)

    # Mark expired
    expired_result = await db.execute(
        update(KnownPerson)
        .where(
            KnownPerson.verification_status != "expired",
            KnownPerson.last_verified_at <= expiry_cutoff,
        )
        .values(verification_status="expired")
    )

    # Mark stale (but not expired)
    stale_result = await db.execute(
        update(KnownPerson)
        .where(
            KnownPerson.verification_status == "fresh",
            KnownPerson.last_verified_at <= stale_cutoff,
            KnownPerson.last_verified_at > expiry_cutoff,
        )
        .values(verification_status="stale")
    )

    await db.commit()
    return {
        "expired": expired_result.rowcount,
        "stale": stale_result.rowcount,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _find_existing(
    db: AsyncSession,
    *,
    linkedin_url: str | None,
    apollo_id: str | None,
    normalized_name: str,
) -> KnownPerson | None:
    """Find an existing known person by linkedin_url, apollo_id, or name."""
    # Priority 1: LinkedIn URL (strongest dedup signal)
    if linkedin_url:
        result = await db.execute(
            select(KnownPerson).where(KnownPerson.linkedin_url == linkedin_url).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    # Priority 2: Apollo ID
    if apollo_id:
        result = await db.execute(
            select(KnownPerson).where(KnownPerson.apollo_id == apollo_id).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    # Priority 3: Normalized name (weaker — only if unique)
    result = await db.execute(
        select(KnownPerson).where(KnownPerson.normalized_name == normalized_name)
    )
    matches = list(result.scalars().all())
    if len(matches) == 1:
        return matches[0]

    return None


async def _ensure_company_association(
    db: AsyncSession,
    known_person_id: uuid.UUID,
    company_name: str,
    normalized_company_name: str,
    *,
    company_domain: str | None = None,
    title_at_company: str | None = None,
) -> None:
    """Ensure a company association exists, creating or updating as needed."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(KnownPersonCompany).where(
            KnownPersonCompany.known_person_id == known_person_id,
            KnownPersonCompany.normalized_company_name == normalized_company_name,
        ).limit(1)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.last_seen_at = now
        if title_at_company:
            existing.title_at_company = title_at_company
        if company_domain:
            existing.company_domain = company_domain
    else:
        kpc = KnownPersonCompany(
            known_person_id=known_person_id,
            company_name=company_name,
            normalized_company_name=normalized_company_name,
            company_domain=company_domain,
            title_at_company=title_at_company,
            is_current=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(kpc)


def _to_candidate_dict(kp: KnownPerson, kpc: KnownPersonCompany) -> dict:
    """Convert a KnownPerson + company association to a candidate dict.

    The output shape matches what the people discovery pipeline expects,
    so cached results integrate seamlessly with live search results.
    """
    return {
        "full_name": kp.full_name,
        "title": kpc.title_at_company or kp.title,
        "department": kp.department,
        "seniority": kp.seniority,
        "linkedin_url": kp.linkedin_url,
        "github_url": kp.github_url,
        "work_email": kp.work_email,
        "apollo_id": kp.apollo_id,
        "profile_data": {
            **(kp.profile_data or {}),
            "from_known_cache": True,
            "known_person_id": str(kp.id),
            "discovery_count": kp.discovery_count,
            "cache_freshness": kp.verification_status or "fresh",
        },
        "github_data": kp.github_data,
        "source": kp.primary_source,
        "company_name": kpc.company_name,
        "company_domain": kpc.company_domain,
    }
