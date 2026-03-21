"""Current-company verification for discovered people."""

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import brave_search_client, crawl4ai_client, public_page_client
from app.config import settings
from app.models.person import Person
from app.utils.company_identity import (
    extract_public_identity_hints,
    is_ambiguous_company_name,
    matches_public_company_identity,
    normalize_company_name,
)

VERIFIED_STATUSES = {"verified"}
BLOCKED_CORROBORATION_HOSTS = {
    "contactout.com",
    "clay.earth",
    "rocketreach.co",
}
AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES = ("co", "company", "limited", "ltd", "corp", "corporation")
PUBLIC_WEB_VERIFICATION_SOURCE = "public_web"


@dataclass
class EmploymentVerificationResult:
    current_company_verified: bool | None
    current_company_verification_status: str
    current_company_verification_source: str | None
    current_company_verification_confidence: int | None
    current_company_verification_evidence: str | None
    current_company_verified_at: datetime | None
    debug: dict | None = None


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _normalize_company_name(value: str | None) -> str:
    return normalize_company_name(value)


def _excerpt(text: str, start: int, end: int, *, window: int = 80) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return _normalize_text(text[left:right])


def _match_patterns(text: str, patterns: list[tuple[str, int]]) -> tuple[int, str] | None:
    for pattern, confidence in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return confidence, _excerpt(text, match.start(), match.end())
    return None


def _has_conflicting_company_variant(text: str, company_name: str) -> bool:
    company_normalized = _normalize_company_name(company_name)
    if not company_normalized or not is_ambiguous_company_name(company_name):
        return False
    first_token = company_normalized.split()[0]
    suffix_group = "|".join(AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES)
    return re.search(rf"\b{re.escape(first_token)}\s+(?:{suffix_group})\b", text, flags=re.IGNORECASE) is not None


def _team_page_lists_candidate(
    text: str,
    *,
    candidate_name: str | None,
    candidate_title: str | None,
) -> bool:
    if not candidate_name:
        return False
    normalized = _normalize_text(text).lower()
    name = _normalize_text(candidate_name).lower()
    title = _normalize_text(candidate_title).lower()
    if not name or name not in normalized:
        return False
    if not title:
        return False
    return title in normalized


def _enrich_public_debug(result: EmploymentVerificationResult, page: dict | None, *, retrieval_url: str) -> None:
    debug = result.debug.copy() if isinstance(result.debug, dict) else {}
    if page:
        debug["retrieval_method"] = page.get("retrieval_method")
        debug["fallback_used"] = bool(page.get("fallback_used"))
    debug["retrieval_url"] = retrieval_url
    result.debug = debug


def _analyze_linkedin_content(content: str, company_name: str) -> EmploymentVerificationResult:
    normalized = _normalize_text(content)
    company_normalized = _normalize_company_name(company_name)
    company_pattern = re.escape(company_normalized).replace(r"\ ", r"\s+")
    haystack = _normalize_company_name(normalized)

    if _has_conflicting_company_variant(normalized.lower(), company_name):
        return EmploymentVerificationResult(
            current_company_verified=False,
            current_company_verification_status="unverified",
            current_company_verification_source="crawl4ai_linkedin",
            current_company_verification_confidence=5,
            current_company_verification_evidence="Conflicting company variant found in public profile evidence.",
            current_company_verified_at=None,
            debug={"kind": "linkedin", "conflict": True},
        )

    positive_patterns = [
        (rf"\b(?:currently|current|works|working)\b[^.:\n]{{0,80}}\b{company_pattern}\b", 96),
        (rf"\b{company_pattern}\b[^.:\n]{{0,80}}\b(?:present|current|today)\b", 94),
        (rf"\b(?:present|current)\b[^.:\n]{{0,80}}\b{company_pattern}\b", 94),
        (rf"\b(?:headline|occupation)\b[^.:\n]{{0,100}}\bat\s+{company_pattern}\b", 92),
    ]

    match = _match_patterns(haystack, positive_patterns)
    if match:
        confidence, evidence = match
        return EmploymentVerificationResult(
            current_company_verified=True,
            current_company_verification_status="verified",
            current_company_verification_source="crawl4ai_linkedin",
            current_company_verification_confidence=confidence,
            current_company_verification_evidence=evidence,
            current_company_verified_at=datetime.now(timezone.utc),
            debug={"kind": "linkedin"},
        )

    return EmploymentVerificationResult(
        current_company_verified=False,
        current_company_verification_status="unverified",
        current_company_verification_source="crawl4ai_linkedin",
        current_company_verification_confidence=35 if company_normalized in haystack else 20,
        current_company_verification_evidence=None,
        current_company_verified_at=None,
        debug={"kind": "linkedin"},
    )


def _analyze_public_content(
    content: str,
    company_name: str,
    *,
    public_url: str | None = None,
    trusted_public_identity_slugs: list[str] | None = None,
    public_page_type: str | None = None,
    candidate_name: str | None = None,
    candidate_title: str | None = None,
) -> EmploymentVerificationResult:
    normalized = _normalize_text(content)
    haystack = _normalize_company_name(normalized)
    company_normalized = _normalize_company_name(company_name)
    company_pattern = re.escape(company_normalized).replace(r"\ ", r"\s+")

    if _has_conflicting_company_variant(normalized.lower(), company_name):
        return EmploymentVerificationResult(
            current_company_verified=False,
            current_company_verification_status="unverified",
            current_company_verification_source=PUBLIC_WEB_VERIFICATION_SOURCE,
            current_company_verification_confidence=5,
            current_company_verification_evidence="Conflicting company variant found in public corroboration.",
            current_company_verified_at=None,
            debug={"kind": "public_web", "conflict": True},
        )

    public_identity_hints = extract_public_identity_hints(public_url)
    if matches_public_company_identity(public_url, company_name, trusted_public_identity_slugs):
        resolved_page_type = public_page_type or public_identity_hints.get("page_type")
        if resolved_page_type == "org_chart_person":
            return EmploymentVerificationResult(
                current_company_verified=True,
                current_company_verification_status="verified",
                current_company_verification_source=PUBLIC_WEB_VERIFICATION_SOURCE,
                current_company_verification_confidence=95,
                current_company_verification_evidence="Trusted The Org company slug matched the target company identity.",
                current_company_verified_at=datetime.now(timezone.utc),
                debug={"kind": "public_web", "public_slug_match": True, "page_type": resolved_page_type},
            )
        if resolved_page_type == "team" and _team_page_lists_candidate(
            normalized,
            candidate_name=candidate_name,
            candidate_title=candidate_title,
        ):
            return EmploymentVerificationResult(
                current_company_verified=True,
                current_company_verification_status="verified",
                current_company_verification_source=PUBLIC_WEB_VERIFICATION_SOURCE,
                current_company_verification_confidence=93,
                current_company_verification_evidence="Trusted The Org team page matched the target company and listed the candidate.",
                current_company_verified_at=datetime.now(timezone.utc),
                debug={"kind": "public_web", "public_slug_match": True, "page_type": resolved_page_type},
            )

    positive_patterns = [
        (rf"\b(?:currently|current|serving|works|working)\b[^.:\n]{{0,100}}\b{company_pattern}\b", 92),
        (rf"\bis\s+(?:an?\s+)?[^.:\n]{{0,80}}\bat\s+{company_pattern}\b", 90),
        (rf"\b{company_pattern}\b[^.:\n]{{0,100}}\bsince\b", 88),
        (rf"\bat\s+{company_pattern}\b", 82),
    ]

    match = _match_patterns(haystack, positive_patterns)
    if match:
        confidence, evidence = match
        return EmploymentVerificationResult(
            current_company_verified=True,
            current_company_verification_status="verified",
            current_company_verification_source=PUBLIC_WEB_VERIFICATION_SOURCE,
            current_company_verification_confidence=confidence,
            current_company_verification_evidence=evidence,
            current_company_verified_at=datetime.now(timezone.utc),
            debug={"kind": "public_web"},
        )

    return EmploymentVerificationResult(
        current_company_verified=False,
        current_company_verification_status="unverified",
        current_company_verification_source=PUBLIC_WEB_VERIFICATION_SOURCE,
        current_company_verification_confidence=25 if company_normalized in haystack else 10,
        current_company_verification_evidence=None,
        current_company_verified_at=None,
        debug={"kind": "public_web"},
    )


def _skipped_result(reason: str) -> EmploymentVerificationResult:
    return EmploymentVerificationResult(
        current_company_verified=None,
        current_company_verification_status="skipped",
        current_company_verification_source=None,
        current_company_verification_confidence=None,
        current_company_verification_evidence=reason,
        current_company_verified_at=None,
        debug={"reason": reason},
    )


def _failed_result(reason: str) -> EmploymentVerificationResult:
    return EmploymentVerificationResult(
        current_company_verified=False,
        current_company_verification_status="failed",
        current_company_verification_source=None,
        current_company_verification_confidence=None,
        current_company_verification_evidence=reason,
        current_company_verified_at=None,
        debug={"reason": reason},
    )


def _apply_verification_result(person: Person, result: EmploymentVerificationResult) -> None:
    person.current_company_verified = result.current_company_verified
    person.current_company_verification_status = result.current_company_verification_status
    person.current_company_verification_source = result.current_company_verification_source
    person.current_company_verification_confidence = result.current_company_verification_confidence
    person.current_company_verification_evidence = result.current_company_verification_evidence
    person.current_company_verified_at = result.current_company_verified_at

    profile_data = person.profile_data if isinstance(person.profile_data, dict) else {}
    debug_payload = {
        "status": result.current_company_verification_status,
        "source": result.current_company_verification_source,
        "confidence": result.current_company_verification_confidence,
        "evidence": result.current_company_verification_evidence,
    }
    if result.debug:
        debug_payload.update(result.debug)
    profile_data["employment_verification"] = debug_payload
    person.profile_data = profile_data


def _verification_sort_key(person: Person) -> tuple[int, int]:
    if person.current_company_verified is True:
        return (0, 0)
    if person.current_company_verification_status == "unverified":
        return (1, 0)
    if person.current_company_verification_status == "failed":
        return (1, 1)
    return (1, 2)


def shortlist_people_for_verification(
    bucketed: dict[str, list[Person]],
    *,
    max_candidates: int,
) -> list[Person]:
    """Pick the top candidates for current-company verification."""
    ordered_buckets = ["recruiters", "hiring_managers", "peers"]
    shortlist: list[Person] = []
    seen: set[uuid.UUID] = set()

    for bucket in ordered_buckets:
        for person in bucketed.get(bucket, [])[:2]:
            if person.id in seen:
                continue
            seen.add(person.id)
            shortlist.append(person)

    if len(shortlist) >= max_candidates:
        return shortlist[:max_candidates]

    for bucket in ordered_buckets:
        for person in bucketed.get(bucket, [])[2:]:
            if person.id in seen:
                continue
            seen.add(person.id)
            shortlist.append(person)
            if len(shortlist) >= max_candidates:
                return shortlist

    return shortlist


async def _verify_person(
    person: Person,
    *,
    company_name: str,
    company_domain: str | None,
    company_public_identity_slugs: list[str] | None = None,
) -> EmploymentVerificationResult:
    if not settings.employment_verify_enabled:
        return _skipped_result("Employment verification is disabled.")
    if not company_name:
        return _skipped_result("No target company available for verification.")
    linkedin_result = _skipped_result("No LinkedIn URL available for verification.")

    if person.linkedin_url:
        linkedin_page = await crawl4ai_client.fetch_profile(
            person.linkedin_url,
            timeout_seconds=settings.employment_verify_timeout_seconds,
        )
        if linkedin_page and linkedin_page.get("content"):
            linkedin_result = _analyze_linkedin_content(linkedin_page["content"], company_name)
            if linkedin_result.current_company_verified:
                return linkedin_result
        else:
            linkedin_result = _failed_result("LinkedIn profile could not be fetched.")

    public_url = ""
    public_page_type = None
    if isinstance(person.profile_data, dict):
        raw_public_url = person.profile_data.get("public_url")
        if isinstance(raw_public_url, str):
            public_url = raw_public_url
        raw_page_type = person.profile_data.get("public_page_type")
        if isinstance(raw_page_type, str):
            public_page_type = raw_page_type

    if (
        public_page_type == "org_chart_person"
        and matches_public_company_identity(public_url, company_name, company_public_identity_slugs)
    ):
        seed_text = " ".join(
            part for part in [getattr(person, "full_name", "") or "", getattr(person, "title", "") or ""] if part
        )
        if not _has_conflicting_company_variant(seed_text.lower(), company_name):
            return EmploymentVerificationResult(
                current_company_verified=True,
                current_company_verification_status="verified",
                current_company_verification_source=PUBLIC_WEB_VERIFICATION_SOURCE,
                current_company_verification_confidence=93,
                current_company_verification_evidence="Trusted public org/company slug matched the target company identity.",
                current_company_verified_at=datetime.now(timezone.utc),
                debug={
                    "kind": "public_web",
                    "public_slug_match": True,
                    "direct_result": True,
                    "retrieval_method": "direct",
                    "retrieval_url": public_url,
                    "fallback_used": False,
                },
            )

    if public_url:
        page = await public_page_client.fetch_page(
            public_url,
            timeout_seconds=settings.employment_verify_timeout_seconds,
        )
        if page and page.get("content"):
            public_result = _analyze_public_content(
                page["content"],
                company_name,
                public_url=public_url,
                trusted_public_identity_slugs=company_public_identity_slugs,
                public_page_type=public_page_type,
                candidate_name=person.full_name,
                candidate_title=person.title,
            )
            if public_result.current_company_verified:
                _enrich_public_debug(public_result, page, retrieval_url=public_url)
                return public_result

    corroboration_results = await brave_search_client.search_employment_sources(
        person.full_name or "",
        company_name,
        company_domain=company_domain,
        public_identity_terms=company_public_identity_slugs,
        limit=3,
    )
    for result in corroboration_results:
        host = urlparse(result["url"]).netloc.lower()
        if host in BLOCKED_CORROBORATION_HOSTS:
            continue
        page = await public_page_client.fetch_page(
            result["url"],
            timeout_seconds=settings.employment_verify_timeout_seconds,
        )
        if not page or not page.get("content"):
            continue
        public_result = _analyze_public_content(
            page["content"],
            company_name,
            public_url=result["url"],
            trusted_public_identity_slugs=company_public_identity_slugs,
            candidate_name=person.full_name,
            candidate_title=person.title,
        )
        if public_result.current_company_verified:
            _enrich_public_debug(public_result, page, retrieval_url=result["url"])
            return public_result

    return linkedin_result


async def verify_people_current_company(
    bucketed: dict[str, list[Person]],
    *,
    company_name: str,
    company_domain: str | None,
    company_public_identity_slugs: list[str] | None = None,
    force: bool = False,
) -> None:
    """Verify current employment for the top-ranked people in a result set."""
    all_people = [person for bucket in bucketed.values() for person in bucket]
    if not all_people:
        return

    shortlist = shortlist_people_for_verification(
        bucketed,
        max_candidates=settings.employment_verify_top_n,
    )
    shortlisted_ids = {person.id for person in shortlist}

    tasks = []
    task_people: list[Person] = []
    for person in shortlist:
        if (
            not force
            and person.current_company_verification_status in {"verified", "unverified", "failed"}
        ):
            continue
        task_people.append(person)
        tasks.append(
            _verify_person(
                person,
                company_name=company_name,
                company_domain=company_domain,
                company_public_identity_slugs=company_public_identity_slugs,
            )
        )

    if tasks:
        results = await asyncio.gather(*tasks)
        for person, result in zip(task_people, results, strict=True):
            _apply_verification_result(person, result)

    for person in all_people:
        if person.id not in shortlisted_ids and person.current_company_verification_status is None:
            _apply_verification_result(person, _skipped_result("Not shortlisted for verification."))
        if person.id in shortlisted_ids and not force and person.current_company_verification_status is None:
            _apply_verification_result(person, _skipped_result("Verification was skipped."))

    for people in bucketed.values():
        people.sort(key=_verification_sort_key)


async def verify_current_company_for_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
) -> Person:
    """Run current-company verification for a single saved person."""
    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise ValueError("Person not found.")

    company_name = person.company.name if person.company else ""
    company_domain = person.company.domain if person.company and getattr(person.company, "domain_trusted", False) else None
    company_public_identity_slugs = getattr(person.company, "public_identity_slugs", None) if person.company else None
    verification = await _verify_person(
        person,
        company_name=company_name,
        company_domain=company_domain,
        company_public_identity_slugs=company_public_identity_slugs,
    )
    _apply_verification_result(person, verification)
    await db.commit()
    await db.refresh(person)
    return person
