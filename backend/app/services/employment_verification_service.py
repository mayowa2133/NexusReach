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

from app.clients import brave_search_client, crawl4ai_client, firecrawl_client
from app.config import settings
from app.models.person import Person
from app.utils.company_identity import is_ambiguous_company_name, normalize_company_name

VERIFIED_STATUSES = {"verified"}
BLOCKED_CORROBORATION_HOSTS = {
    "contactout.com",
    "clay.earth",
    "rocketreach.co",
}
AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES = ("co", "company", "limited", "ltd", "corp", "corporation")


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


def _analyze_public_content(content: str, company_name: str) -> EmploymentVerificationResult:
    normalized = _normalize_text(content)
    haystack = _normalize_company_name(normalized)
    company_normalized = _normalize_company_name(company_name)
    company_pattern = re.escape(company_normalized).replace(r"\ ", r"\s+")

    if _has_conflicting_company_variant(normalized.lower(), company_name):
        return EmploymentVerificationResult(
            current_company_verified=False,
            current_company_verification_status="unverified",
            current_company_verification_source="firecrawl_public_web",
            current_company_verification_confidence=5,
            current_company_verification_evidence="Conflicting company variant found in public corroboration.",
            current_company_verified_at=None,
            debug={"kind": "public_web", "conflict": True},
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
            current_company_verification_source="firecrawl_public_web",
            current_company_verification_confidence=confidence,
            current_company_verification_evidence=evidence,
            current_company_verified_at=datetime.now(timezone.utc),
            debug={"kind": "public_web"},
        )

    return EmploymentVerificationResult(
        current_company_verified=False,
        current_company_verification_status="unverified",
        current_company_verification_source="firecrawl_public_web",
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
) -> EmploymentVerificationResult:
    if not settings.employment_verify_enabled:
        return _skipped_result("Employment verification is disabled.")
    if not company_name:
        return _skipped_result("No target company available for verification.")
    if not person.linkedin_url:
        return _skipped_result("No LinkedIn URL available for verification.")

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

    if not settings.firecrawl_base_url:
        return linkedin_result

    corroboration_results = await brave_search_client.search_employment_sources(
        person.full_name or "",
        company_name,
        company_domain=company_domain,
        limit=3,
    )
    for result in corroboration_results:
        host = urlparse(result["url"]).netloc.lower()
        if host in BLOCKED_CORROBORATION_HOSTS:
            continue
        page = await firecrawl_client.scrape_url(
            result["url"],
            timeout_seconds=settings.employment_verify_timeout_seconds,
        )
        if not page or not page.get("content"):
            continue
        public_result = _analyze_public_content(page["content"], company_name)
        if public_result.current_company_verified:
            return public_result

    return linkedin_result


async def verify_people_current_company(
    bucketed: dict[str, list[Person]],
    *,
    company_name: str,
    company_domain: str | None,
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
    verification = await _verify_person(
        person,
        company_name=company_name,
        company_domain=company_domain,
    )
    _apply_verification_result(person, verification)
    await db.commit()
    await db.refresh(person)
    return person
