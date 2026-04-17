"""People discovery service for company and job-aware search."""

import asyncio
import copy
import logging
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, TypeVar
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import apollo_client, github_client, proxycurl_client, search_router_client, tavily_search_client, theorg_client
from app.models.company import Company
from app.models.job import Job
from app.models.person import Person
from app.services import linkedin_graph_service
from app.services.employment_verification_service import verify_people_current_company
from app.services.theorg_discovery_service import discover_theorg_candidates
from app.utils.company_identity import (
    build_public_identity_hints,
    canonical_company_display_name,
    effective_public_identity_slugs,
    extract_public_identity_hints,
    is_ambiguous_company_name,
    is_compatible_public_identity_slug,
    matches_public_company_identity,
    normalize_company_name,
    should_trust_company_enrichment,
)
from app.utils.job_context import (
    JobContext,
    build_job_geo_terms,
    extract_job_context,
    normalize_job_locations,
)
from app.utils.linkedin import normalize_linkedin_url
from app.utils.relevance_scorer import score_candidate_relevance

logger = logging.getLogger(__name__)
T = TypeVar("T")

RECRUITER_TITLE_KEYWORDS = (
    "recruiter",
    "hiring coordinator",
    "hiring",
    "recruiting",
    "recruiting coordinator",
    "recruiting partner",
    "recruitment",
    "talent acquisition",
    "talent operations",
    "talent partner",
    "talent scout",
    "sourcer",
    "technical sourcer",
    "campus recruiter",
    "university recruiter",
    "early careers",
    "early talent",
    "emerging talent",
    "university programs",
)
GENERIC_PEOPLE_TITLE_KEYWORDS = (
    "human resources",
    "people operations",
    "people ops",
    "people partner",
    "hr business partner",
    "hrbp",
)
MANAGER_TITLE_KEYWORDS = (
    "manager",
    "director",
    "head",
    "vice president",
    "vp",
)
CONTROLLED_LEAD_KEYWORDS = (
    "tech lead",
    "team lead",
    "engineering lead",
)
DIRECTOR_PLUS_KEYWORDS = (
    "director",
    "head",
    "vice president",
    "vp",
    "managing director",
    "chief",
)
ROLE_HINT_KEYWORDS = (
    "engineer",
    "developer",
    "scientist",
    "analyst",
    "recruiter",
    "talent",
    "sourcer",
    "manager",
    "director",
    "lead",
    "partner",
)
CURRENT_TRUSTED_SOURCES = {
    "apollo",
    "proxycurl",
    "brave_hiring_team",
    "serper_hiring_team",
}
CURRENT_TRUSTED_PUBLIC_HOSTS = {
    "theorg.com",
    "www.theorg.com",
}
PUBLIC_WEB_SOURCES = {
    "brave_public_web",
    "serper_public_web",
    "tavily_public_web",
}
SOURCE_PRIORITY = {
    "apollo": 0,
    "proxycurl": 1,
    "brave_hiring_team": 1,
    "serper_hiring_team": 1,
    "theorg_traversal": 2,
    "brave_search": 3,
    "serper_search": 3,
    "google_cse": 3,
    "brave_public_web": 4,
    "serper_public_web": 4,
    "tavily_public_web": 4,
    "github": 4,
}
SENIOR_MANAGER_LEVELS = {"staff", "principal", "manager", "director", "vp", "executive"}
FORMER_COMPANY_PATTERNS = (
    r"\bformer\b",
    r"\bformerly\b",
    r"\bpreviously\b",
    r"\bex[-\s]",
    r"\bpast\b",
)
AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES = {"co", "company", "limited", "ltd", "corp", "corporation"}
COMPANY_NEGATIVE_TERMS = {
    "zip": {"ziprecruiter"},
}
PUBLIC_DIRECTORY_TERMS = {
    "email & phone",
    "phone number",
    "staff directory",
    "company profile",
    "contact info",
    "contact information",
    "directory",
}
WEAK_TITLE_PLACEHOLDERS = {
    "employee",
    "member",
    "team member",
    "staff member",
    "teammate",
}
RECRUITER_ADJACENT_KEYWORDS = (
    "talent acquisition",
    "talent operations",
    "talent partner",
    "early talent",
    "early careers",
    "university programs",
    "recruiting coordinator",
    "recruitment",
)
SENIOR_IC_FALLBACK_KEYWORDS = (
    "staff engineer",
    "principal engineer",
    "member of technical staff",
    "technical staff",
    "architect",
)
TALENT_TITLE_KEYWORDS = (
    "talent",
    "sourcer",
    "sourcing",
    "talent partner",
    "talent operations",
    "talent coordinator",
    "people partner",
    "employer brand",
)
DEFAULT_TARGET_COUNT_PER_BUCKET = 3
MAX_TARGET_COUNT_PER_BUCKET = 10
SENIORITY_ORDER = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "senior": 3,
    "staff": 4,
    "principal": 4,
    "lead": 3,
    "manager": 5,
    "director": 6,
    "vp": 7,
    "executive": 8,
}


def _clamp_target_count_per_bucket(value: int | None) -> int:
    if value is None:
        return DEFAULT_TARGET_COUNT_PER_BUCKET
    return max(1, min(int(value), MAX_TARGET_COUNT_PER_BUCKET))


def _search_limit_for_target(target_count_per_bucket: int) -> int:
    return min(50, max(15, target_count_per_bucket * 5))


def _prepare_limit_for_target(target_count_per_bucket: int) -> int:
    return min(40, max(10, target_count_per_bucket * 4))


def _minimum_results_for_target(target_count_per_bucket: int) -> int:
    return max(1, min(target_count_per_bucket, 5))


def _count_linkedin_candidates(candidates: list[dict]) -> int:
    return sum(1 for candidate in candidates if candidate.get("linkedin_url"))


def _needs_more_bucket_candidates(candidates: list[dict], *, target_count_per_bucket: int) -> bool:
    return (
        len(candidates) < target_count_per_bucket
        or _count_linkedin_candidates(candidates) < min(target_count_per_bucket, len(candidates))
    )


def _needs_more_bucket_size_only(candidates: list[dict], *, target_count_per_bucket: int) -> bool:
    return len(candidates) < target_count_per_bucket


def _normalize_identity(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _normalize_name_for_matching(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_only.lower()))


def _dedupe_text(values: list[str] | None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        clean = " ".join((value or "").split()).strip()
        normalized = clean.lower()
        if not clean or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(clean)
    return ordered


def _bucket_geo_terms(context: JobContext | None, *, bucket: str) -> list[str]:
    if not context:
        return []
    base_terms = _dedupe_text(context.job_geo_terms or context.job_locations)
    if not base_terms:
        return []

    full_location = base_terms[:1]
    city_terms = base_terms[1:2] if len(base_terms) > 1 else []
    remaining = base_terms[2:] if len(base_terms) > 2 else []
    country_terms = [term for term in remaining if term in {"Canada", "United States", "United Kingdom"}]
    metro_terms = [term for term in remaining if "Area" in term or term == "GTA"]
    region_terms = [
        term
        for term in remaining
        if term not in country_terms and term not in metro_terms
    ]

    if bucket == "recruiters":
        return _dedupe_text(city_terms + region_terms + country_terms + metro_terms + full_location)
    return _dedupe_text(city_terms + metro_terms + region_terms + country_terms + full_location)


def _candidate_location_value(data: dict) -> str | None:
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    return (
        data.get("location")
        or data.get("city")
        or profile_data.get("location")
        or None
    )


def _candidate_geo_signal_match(data: dict, *, context: JobContext | None) -> bool:
    if _location_match_rank(data, context=context) == 0:
        return True
    if not context:
        return False

    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    haystack = " ".join(
        part
        for part in [
            data.get("title", ""),
            data.get("snippet", ""),
            _candidate_location_value(data) or "",
            str(profile_data.get("linkedin_result_title") or ""),
        ]
        if part
    ).lower()
    if not haystack:
        return False

    geo_terms = _dedupe_text((context.job_geo_terms or []) + _bucket_geo_terms(context, bucket="hiring_managers"))
    if not geo_terms:
        return False

    strong_terms = [
        term
        for term in geo_terms
        if term
        and term not in {"Canada", "United States", "United Kingdom"}
        and "," not in term
    ]
    if any(_keyword_in_text(term.lower(), haystack) for term in strong_terms):
        return True

    weak_terms = [term for term in geo_terms if term in {"Canada", "United States", "United Kingdom"}]
    if weak_terms and any(_keyword_in_text(term.lower(), haystack) for term in weak_terms):
        title = data.get("title", "") or ""
        snippet = data.get("snippet", "") or ""
        return _is_manager_like(title) or _is_manager_like(snippet)

    return False


def _debug_candidate_summary(data: dict) -> dict[str, Any]:
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    return {
        "full_name": data.get("full_name"),
        "title": data.get("title"),
        "source": data.get("source"),
        "linkedin_url": data.get("linkedin_url"),
        "location": _candidate_location_value(data),
        "employment_status": data.get("_employment_status"),
        "org_level": data.get("_org_level"),
        "search_provider": profile_data.get("search_provider"),
        "search_query": profile_data.get("search_query"),
        "search_query_index": profile_data.get("search_query_index"),
        "search_geo_terms": profile_data.get("search_geo_terms"),
    }


def _debug_person_summary(person: Person) -> dict[str, Any]:
    profile_data = person.profile_data if isinstance(person.profile_data, dict) else {}
    return {
        "id": str(person.id) if person.id else None,
        "full_name": person.full_name,
        "title": person.title,
        "person_type": person.person_type,
        "linkedin_url": person.linkedin_url,
        "location": profile_data.get("location"),
        "usefulness_score": getattr(person, "usefulness_score", None),
        "match_quality": getattr(person, "match_quality", None),
        "match_reason": getattr(person, "match_reason", None),
        "company_match_confidence": getattr(person, "company_match_confidence", None),
        "employment_status": getattr(person, "employment_status", None),
        "org_level": getattr(person, "org_level", None),
        "search_query": profile_data.get("search_query"),
        "search_provider": profile_data.get("search_provider"),
    }


def _contains_any_keyword(text: str | None, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize_identity(text)
    return any(keyword in normalized for keyword in keywords)


def _identity_tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _candidate_key(data: dict) -> str:
    linkedin_url = data.get("linkedin_url") or ""
    apollo_id = data.get("apollo_id") or ""
    full_name = _normalize_identity(data.get("full_name"))
    title = _normalize_identity(data.get("title"))
    if linkedin_url:
        return f"linkedin:{linkedin_url}"
    if apollo_id:
        return f"apollo:{apollo_id}"
    return f"name:{full_name}|title:{title}"


def _keyword_in_text(keyword: str, text: str) -> bool:
    if not text:
        return False
    if keyword == "backend":
        return "backend" in text or "back-end" in text or "server-side" in text
    if keyword == "decisioning":
        return "decisioning" in text or "decision engine" in text or "eligibility" in text
    return keyword.replace("_", " ") in text


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _name_match_score(candidate_name: str | None, linkedin_name: str | None) -> int:
    candidate_tokens = _normalize_name_for_matching(candidate_name).split()
    linkedin_tokens = _normalize_name_for_matching(linkedin_name).split()
    if len(candidate_tokens) < 2 or len(linkedin_tokens) < 2:
        return 0

    candidate_first, candidate_last = candidate_tokens[0], candidate_tokens[-1]
    linkedin_first, linkedin_last = linkedin_tokens[0], linkedin_tokens[-1]

    if candidate_last == linkedin_last:
        if candidate_first != linkedin_first:
            return 0
        return 100 if candidate_tokens == linkedin_tokens else 96

    if (
        len(candidate_tokens) == 2
        and len(linkedin_tokens) == 2
        and candidate_first == linkedin_last
        and candidate_last == linkedin_first
    ):
        return 92

    if candidate_first != linkedin_first:
        return 0

    if len(candidate_last) == 1 and linkedin_last.startswith(candidate_last):
        return 90
    if len(linkedin_last) == 1 and candidate_last.startswith(linkedin_last):
        return 90
    return 0


def _linkedin_backfill_name_variants(full_name: str | None) -> list[str]:
    raw = (full_name or "").strip()
    if not raw:
        return []

    variants: list[str] = []
    normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized and normalized != raw:
        variants.append(normalized)

    comma_parts = [part.strip() for part in raw.split(",", 1)]
    if len(comma_parts) == 2 and all(comma_parts):
        variants.append(f"{comma_parts[1]} {comma_parts[0]}")

    raw_tokens = [token.strip() for token in re.split(r"\s+", raw) if token.strip()]
    cleaned_tokens = [re.sub(r"[^A-Za-z0-9'-]", "", token) for token in raw_tokens]
    cleaned_tokens = [token for token in cleaned_tokens if token]
    if len(cleaned_tokens) >= 3:
        without_middle_initials = [
            cleaned_tokens[0],
            *[token for token in cleaned_tokens[1:-1] if len(token) > 1],
            cleaned_tokens[-1],
        ]
        if len(without_middle_initials) >= 2:
            variants.append(" ".join(without_middle_initials))

    normalized_tokens = _normalize_name_for_matching(raw).split()
    if len(normalized_tokens) == 2:
        first, last = normalized_tokens
        variants.append(f"{last.title()} {first.title()}")

    ordered: list[str] = []
    seen: set[str] = set()
    canonical = _normalize_name_for_matching(raw)
    for variant in variants:
        clean_variant = " ".join(variant.split()).strip()
        if not clean_variant:
            continue
        normalized_variant = _normalize_name_for_matching(clean_variant)
        if not normalized_variant or normalized_variant == canonical or normalized_variant in seen:
            continue
        seen.add(normalized_variant)
        ordered.append(clean_variant)
    return ordered[:3]


def _public_profile_url(data: dict) -> str:
    profile_data = data.get("profile_data") or {}
    public_url = profile_data.get("public_url")
    return public_url if isinstance(public_url, str) else ""


def _public_profile_host(data: dict) -> str:
    public_url = _public_profile_url(data)
    if not public_url:
        return ""
    return urlparse(public_url).netloc.lower()


def _linkedin_profile_host(data: dict) -> str:
    linkedin_url = data.get("linkedin_url") or ""
    if not linkedin_url:
        return ""
    return urlparse(linkedin_url).netloc.lower()


def _is_linkedin_public_profile(data: dict) -> bool:
    hosts = {
        _public_profile_host(data),
        _linkedin_profile_host(data),
    }
    return any("linkedin.com" in host for host in hosts if host)


def _mentions_company(text: str, company_name: str) -> bool:
    company_tokens = normalize_company_name(company_name).split()
    text_tokens = _identity_tokens(text)
    if not company_tokens or not text_tokens:
        return False

    negative_terms = COMPANY_NEGATIVE_TERMS.get(company_tokens[0], set())
    if any(term in "".join(text_tokens) for term in negative_terms):
        return False

    company_length = len(company_tokens)
    for index in range(len(text_tokens) - company_length + 1):
        window = text_tokens[index:index + company_length]
        if window != company_tokens:
            continue
        if (
            is_ambiguous_company_name(company_name)
            and company_length == 1
            and index + company_length < len(text_tokens)
            and text_tokens[index + company_length] in AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES
        ):
            continue
        return True
    return False


def _role_like_title(title: str) -> bool:
    normalized = _normalize_identity(title)
    return any(keyword in normalized for keyword in ROLE_HINT_KEYWORDS)


def _title_looks_like_company_only(title: str, company_name: str) -> bool:
    normalized_title = _normalize_identity(title)
    normalized_company = _normalize_identity(company_name)
    if not normalized_title or not normalized_company:
        return False
    if normalized_title == normalized_company:
        return True

    title_tokens = _identity_tokens(normalized_title)
    company_tokens = _identity_tokens(normalized_company)
    if not title_tokens or not company_tokens:
        return False
    suffixes = {"inc", "llc", "lp", "l.p", "ltd", "limited", "corp", "corporation", "co"}
    filtered_title = [token for token in title_tokens if token not in suffixes]
    return filtered_title == company_tokens


def _title_is_weak(title: str | None, company_name: str) -> bool:
    normalized_title = _normalize_identity(title)
    if not normalized_title:
        return True
    if normalized_title in WEAK_TITLE_PLACEHOLDERS:
        return True
    return _title_looks_like_company_only(normalized_title, company_name)


def _is_recruiter_like(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    if not normalized:
        return False
    if not _contains_any_keyword(normalized, RECRUITER_TITLE_KEYWORDS):
        return False
    generic_only = _contains_any_keyword(normalized, GENERIC_PEOPLE_TITLE_KEYWORDS) and not any(
        keyword in normalized for keyword in ("recruit", "talent acquisition", "talent operations", "talent partner", "sourcer", "early talent", "early careers", "emerging talent", "university", "hiring")
    )
    return not generic_only


def _is_manager_like(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    if not normalized:
        return False
    return _contains_any_keyword(normalized, MANAGER_TITLE_KEYWORDS + CONTROLLED_LEAD_KEYWORDS)


def _generic_manager_title(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    return normalized in {"manager", "director", "head", "vice president", "vp"}


def _manager_candidate_has_engineering_context(data: dict, *, context: JobContext | None) -> bool:
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    location = data.get("location", "") or profile_data.get("location", "") or ""
    result_title = profile_data.get("linkedin_result_title", "") or ""
    public_snippet = profile_data.get("public_snippet", "") or ""
    haystack = " ".join(part for part in [title, snippet, result_title, public_snippet, location] if part).lower()

    if any(keyword in haystack for keyword in ("engineering", "software", "developer", "full stack", "fullstack", "platform")):
        return True
    if context:
        keywords = list(dict.fromkeys((context.team_keywords or []) + (context.domain_keywords or [])))
        if any(_keyword_in_text(keyword.lower(), haystack) for keyword in keywords if keyword):
            return True
    return False


def _is_adjacent_recruiter_like(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    if not normalized:
        return False
    return any(keyword in normalized for keyword in RECRUITER_ADJACENT_KEYWORDS)


def _is_senior_ic_fallback(title: str | None) -> bool:
    normalized = _normalize_identity(title)
    if not normalized:
        return False
    if normalized.startswith("senior ") and any(role in normalized for role in ("engineer", "scientist", "developer")):
        return True
    return any(keyword in normalized for keyword in SENIOR_IC_FALLBACK_KEYWORDS)


def _strip_seniority_prefix(title: str | None) -> str:
    cleaned = (title or "").strip()
    cleaned = re.sub(
        r"^(?:senior|sr\.?|junior|jr\.?|staff|principal|lead|associate|entry[- ]level|new grad(?:uate)?|intern)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+\b(i|ii|iii|iv)\b$", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip()


# IC roles where "manager" does not mean people-management seniority.
_IC_MANAGER_PATTERNS = (
    r"\bproduct manager\b",
    r"\bprogram manager\b",
    r"\bproject manager\b",
    r"\baccount manager\b",
    r"\bcommunity manager\b",
    r"\bcontent manager\b",
    r"\bcampaign manager\b",
    r"\bpartnership manager\b",
    r"\bsuccess manager\b",
    r"\brelationship manager\b",
)


def _candidate_seniority_level(data: dict) -> str:
    explicit = _normalize_identity(str(data.get("seniority") or ""))
    if explicit in SENIORITY_ORDER:
        return explicit

    haystack = " ".join(
        part for part in [data.get("title", ""), data.get("snippet", "")]
        if part
    ).lower()

    # Check for IC "manager" roles first — these should be sized by their
    # own seniority prefix (Senior PM → senior, Associate PM → junior),
    # NOT treated as people-managers.
    is_ic_manager = any(re.search(p, haystack) for p in _IC_MANAGER_PATTERNS)

    patterns = (
        (r"\bintern\b", "intern"),
        (r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\bassociate\b|\bnew grad\b|\bapm\b", "junior"),
        (r"\bsenior\b|\bsr\.?\b", "senior"),
        (r"\bstaff\b", "staff"),
        (r"\bprincipal\b", "principal"),
        (r"\blead\b", "lead"),
        (r"\bengineering manager\b", "manager"),
        (r"\bdirector\b", "director"),
        (r"\bvp\b|\bvice president\b", "vp"),
        (r"\bchief\b|\bc-level\b", "executive"),
    )
    for pattern, level in patterns:
        if re.search(pattern, haystack):
            return level

    # Bare "manager" — only counts as people-manager if NOT an IC title
    if re.search(r"\bmanager\b", haystack):
        return "mid" if is_ic_manager else "manager"

    return "mid"


def _seniority_fit_rank(data: dict, *, bucket: str, context: JobContext | None) -> int:
    if not context:
        return 1

    if bucket == "recruiters":
        title = data.get("title", "") or ""
        snippet = data.get("snippet", "") or ""
        if _is_recruiter_like(title) or _is_recruiter_like(snippet):
            return 0
        return 1

    candidate_level = _candidate_seniority_level(data)
    candidate_rank = SENIORITY_ORDER.get(candidate_level, 2)

    if bucket == "hiring_managers":
        if data.get("_senior_ic_fallback"):
            return 2
        return 0 if candidate_rank >= SENIORITY_ORDER["manager"] else 1

    target_level = context.seniority if context.seniority in SENIORITY_ORDER else ("junior" if context.early_career else "mid")
    target_rank = SENIORITY_ORDER.get(target_level, 2)
    distance = abs(candidate_rank - target_rank)
    if distance == 0:
        return 0
    if distance == 1:
        return 1
    return 2


def _compute_usefulness_score(
    data: dict,
    *,
    bucket: str,
    context: JobContext | None,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> int:
    """Compute a 0-100 usefulness score for ranking people results.

    Factors:
    - Company verification (0-25 pts)
    - Team/department relevance (0-20 pts)
    - Title/role fit for bucket (0-20 pts)
    - Seniority match (0-10 pts)
    - Location match (0-10 pts)
    - Recency for peers (0-5 pts)
    - LinkedIn profile presence (0-5 pts)
    - Source quality (0-5 pts)
    """
    score = 0

    # --- Company verification (0-25) ---
    employment_status = data.get("_employment_status")
    if not employment_status:
        employment_status = _classify_employment_status(data, company_name, public_identity_slugs)
    if employment_status == "current":
        trusted = _trusted_public_match(data, company_name, public_identity_slugs)
        source = data.get("source", "")
        if source in CURRENT_TRUSTED_SOURCES or trusted:
            score += 25
        else:
            score += 20
    elif employment_status == "ambiguous":
        score += 10
    # former gets 0

    # --- Team/department relevance (0-20) ---
    if context:
        haystack = " ".join(
            part for part in [
                data.get("title", ""),
                data.get("snippet", ""),
                data.get("department", ""),
            ] if part
        ).lower()
        team_keyword_hits = sum(
            1 for keyword in context.team_keywords + context.domain_keywords
            if _keyword_in_text(keyword, haystack)
        )
        if team_keyword_hits >= 2:
            score += 20
        elif team_keyword_hits == 1:
            score += 14
        elif context.department.replace("_", " ") in haystack:
            score += 10
        else:
            score += 3
    else:
        score += 10  # no context = neutral

    # --- Title/role fit for bucket (0-20) ---
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    if bucket == "recruiters":
        if _is_recruiter_like(title):
            score += 20
        elif _is_recruiter_like(snippet):
            score += 14
        elif _contains_any_keyword(title, TALENT_TITLE_KEYWORDS):
            score += 10
        else:
            score += 2
        recruiter_haystack = f"{title} {snippet}".lower()
        if "canada" in recruiter_haystack and any(keyword in recruiter_haystack for keyword in ("lead", "head", "manager", "director")):
            score += 4
    elif bucket == "hiring_managers":
        if _is_manager_like(title):
            if context and any(
                _keyword_in_text(kw, title.lower())
                for kw in context.team_keywords
            ):
                score += 20  # team-specific manager
            else:
                score += 14  # generic manager at company
        elif _is_manager_like(snippet):
            score += 10
        elif data.get("_senior_ic_fallback"):
            score += 6
        else:
            score += 2
    else:  # peers
        if not data.get("_weak_title") and _role_like_title(title):
            score += 18
        elif _role_like_title(title):
            score += 12
        elif data.get("_weak_title"):
            score += 4
        else:
            score += 8

    # --- Seniority match (0-10) ---
    seniority_rank = _seniority_fit_rank(data, bucket=bucket, context=context)
    if seniority_rank == 0:
        score += 10
    elif seniority_rank == 1:
        score += 7
    else:
        score += 3

    # --- Location match (0-10) ---
    if _location_match_rank(data, context=context) == 0:
        score += 10
    # unknown or no-match gets 0

    # --- Recency for peers (0-5) ---
    if bucket == "peers" and _recency_rank(data) == 0:
        score += 5

    # --- LinkedIn presence (0-5) ---
    if data.get("linkedin_url"):
        score += 5

    # --- Source quality (0-5) ---
    source_priority = _source_rank(data.get("source"))
    if source_priority <= 1:
        score += 5
    elif source_priority <= 3:
        score += 3
    else:
        score += 1

    return min(100, max(0, score))


def _peer_title_variants_for_seniority(title: str, seniority: str) -> tuple[list[str], list[str]]:
    base_title = _strip_seniority_prefix(title)
    if not base_title:
        return [], []

    same_level: list[str]
    adjacent_level: list[str]

    if seniority == "intern":
        same_level = [f"{base_title} Intern", "Software Engineering Intern", base_title]
        adjacent_level = [f"Junior {base_title}", f"Associate {base_title}"]
    elif seniority == "junior":
        same_level = [
            f"Junior {base_title}",
            f"Associate {base_title}",
            f"Entry Level {base_title}",
            f"{base_title} I",
            base_title,
        ]
        adjacent_level = [f"Mid-Level {base_title}", f"Senior {base_title}"]
    elif seniority == "senior":
        same_level = [f"Senior {base_title}", base_title]
        adjacent_level = [f"Staff {base_title}", f"Principal {base_title}"]
    elif seniority in {"staff", "principal"}:
        same_level = [f"Staff {base_title}", f"Principal {base_title}", f"Senior {base_title}"]
        adjacent_level = [base_title]
    else:
        same_level = [base_title]
        adjacent_level = [f"Junior {base_title}", f"Senior {base_title}", f"Associate {base_title}"]

    def _dedupe_variants(values: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for variant in values:
            normalized = _normalize_identity(variant)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(variant)
        return ordered

    return _dedupe_variants(same_level), _dedupe_variants(adjacent_level)


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


def _linkedin_backfill_metadata(
    data: dict,
    *,
    status: str,
    confidence: int | None = None,
    source: str = "search_router",
    strategy: str | None = None,
) -> dict:
    profile_data = dict(data.get("profile_data") or {})
    profile_data["linkedin_backfill_status"] = status
    profile_data["linkedin_backfill_source"] = source
    if confidence is not None:
        profile_data["linkedin_backfill_confidence"] = confidence
    if strategy:
        profile_data["linkedin_backfill_strategy"] = strategy
    return profile_data


def _recover_title_from_snippet(
    data: dict,
    *,
    company_name: str,
) -> tuple[str, int] | None:
    company_pattern = re.escape(company_name).replace(r"\ ", r"\s+")
    full_name = re.escape(data.get("full_name", "")).replace(r"\ ", r"\s+")
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    texts = [
        data.get("snippet", ""),
        data.get("title", ""),
        profile_data.get("linkedin_result_title", ""),
        profile_data.get("public_snippet", ""),
    ]
    public_url = _public_profile_url(data)
    is_theorg_public_url = "theorg.com" in (public_url or "")
    patterns = [
        rf"\b(?:currently serving as|serving as|works as|working as|is)\s+(?:an?\s+)?(?P<title>[^.;|,\n]+?)\s+(?:at|@)\s+{company_pattern}\b",
        rf"\b(?P<title>[^.;|,\n]+?)\s*@\s*{company_pattern}\b",
        rf"\b(?P<title>[^.;|,\n]+?)\s+at\s+{company_pattern}\b",
    ]

    for text in texts:
        normalized = " ".join((text or "").split())
        if not normalized:
            continue
        if not is_theorg_public_url and _is_recruiter_like(normalized):
            if re.search(
                rf"\babout\b.*\bi\s+(?:lead|manage)\b[^.;\n]{{0,80}}\b(?:talent acquisition|recruit(?:ing|ment))\b[^.;\n]{{0,80}}\b(?:at|for)\s+{company_pattern}\b",
                normalized,
                flags=re.IGNORECASE,
            ):
                if re.search(r"\b(canada|toronto|greater toronto area|gta)\b", normalized, flags=re.IGNORECASE):
                    return "Talent Acquisition Lead, Canada", 74
                return "Talent Acquisition Lead", 72
            if re.search(
                r"\babout\b.*\bresponsible for hiring\b[^.;\n]{0,80}\b(?:canada|toronto|greater toronto area|gta)\b",
                normalized,
                flags=re.IGNORECASE,
            ):
                return "Talent Acquisition Lead, Canada", 72
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue
            recovered = match.group("title").strip(" -,:|")
            if full_name:
                recovered = re.sub(rf"^{full_name}\s+(?:is|was)\s+", "", recovered, flags=re.IGNORECASE)
            recovered = re.sub(r"^(?:a|an)\s+", "", recovered, flags=re.IGNORECASE)
            recovered = recovered.strip(" -,:|")
            if recovered and not _title_is_weak(recovered, company_name) and _role_like_title(recovered):
                confidence = 75 if text == texts[0] else 65
                return recovered, confidence
        if not is_theorg_public_url and _is_recruiter_like(normalized):
            if re.search(r"\b(?:lead|head|manager|director)\b[^.;\n]{0,40}\b(?:talent acquisition|recruit)\b", normalized, flags=re.IGNORECASE):
                return "Talent Acquisition Leader", 60
            return "Talent Acquisition", 55
        if not is_theorg_public_url and _is_manager_like(normalized) and "engineering" in normalized:
            if "director" in normalized:
                return "Director of Engineering", 60
            return "Engineering Manager", 55
    return None


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

    page = await theorg_client.fetch_page(public_url, timeout_seconds=20)
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


def _linkedin_company_match(candidate: dict, company_name: str) -> bool:
    profile_data = candidate.get("profile_data") or {}
    result_title = profile_data.get("linkedin_result_title")
    texts = [candidate.get("snippet", ""), candidate.get("title", ""), result_title]
    return any(_mentions_company(str(text), company_name) for text in texts if text)


def _linkedin_role_match(candidate: dict, *, bucket: str) -> bool:
    title = candidate.get("title", "") or ""
    snippet = candidate.get("snippet", "") or ""
    person_type = _classify_person(title, source=candidate.get("source", ""), snippet=snippet)
    if bucket == "recruiters":
        return person_type == "recruiter" and (_is_recruiter_like(title) or _is_recruiter_like(snippet))
    if bucket == "hiring_managers":
        return person_type == "hiring_manager" and (_is_manager_like(title) or _is_manager_like(snippet))
    return person_type == "peer"


def _linkedin_title_match_score(
    candidate: dict,
    match: dict,
    *,
    company_name: str,
    bucket: str,
) -> int:
    candidate_title = candidate.get("title", "") or ""
    profile_data = match.get("profile_data") or {}
    result_title = profile_data.get("linkedin_result_title", "") or ""
    texts = [match.get("title", "") or "", result_title, match.get("snippet", "") or ""]

    if candidate_title and not _title_is_weak(candidate_title, company_name):
        normalized_candidate = _normalize_identity(candidate_title)
        if any(normalized_candidate and normalized_candidate in _normalize_identity(text) for text in texts if text):
            return 4

        candidate_tokens = {
            token
            for token in _identity_tokens(candidate_title)
            if token not in {"senior", "staff", "principal", "global", "technical"}
        }
        if candidate_tokens:
            best_overlap = 0
            for text in texts:
                text_tokens = set(_identity_tokens(text))
                if not text_tokens:
                    continue
                best_overlap = max(best_overlap, len(candidate_tokens & text_tokens))
            if best_overlap >= 2:
                return 3

    if bucket == "recruiters" and any(_is_recruiter_like(text) for text in texts):
        return 2
    if bucket == "hiring_managers" and any(_is_manager_like(text) for text in texts):
        return 2
    if bucket == "peers" and any(_classify_person(str(text), snippet=match.get("snippet", "")) == "peer" for text in texts if text):
        return 1
    return 0


def _linkedin_backfill_search_titles(candidate: dict, *, bucket: str, company_name: str, context: JobContext | None = None) -> list[str]:
    titles: list[str] = []
    current_title = (candidate.get("title") or "").strip()
    if current_title and not _title_is_weak(current_title, company_name):
        titles.append(current_title)

    if bucket == "recruiters":
        titles.extend(
            [
                "talent acquisition partner",
                "technical recruiter",
                "recruiter",
            ]
        )
    elif bucket == "hiring_managers":
        dept = context.department if context else ""
        if dept == "product_management":
            titles.extend(
                [
                    "group product manager",
                    "senior product manager",
                    "director of product management",
                    "head of product",
                ]
            )
        elif dept == "design":
            titles.extend(
                [
                    "design manager",
                    "head of design",
                    "senior design manager",
                ]
            )
        else:
            titles.extend(
                [
                    "engineering manager",
                    "software engineering manager",
                    "director engineering",
                    "senior director engineering",
                ]
            )
    elif bucket == "peers":
        dept = context.department if context else ""
        if dept == "product_management":
            titles.extend(["product manager", "associate product manager", "technical program manager"])
        elif dept == "design":
            titles.extend(["product designer", "ux designer", "ui designer"])
        else:
            titles.extend(["software engineer", "senior software engineer"])

    ordered: list[str] = []
    seen: set[str] = set()
    for title in titles:
        normalized = _normalize_identity(title)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(title)
    return ordered[:4]


def _linkedin_backfill_team_keywords(candidate: dict, *, bucket: str) -> list[str]:
    profile_data = candidate.get("profile_data") or {}
    keywords: list[str] = []

    team_name = str(profile_data.get("theorg_team_name") or "").strip()
    if team_name:
        keywords.append(team_name)

    team_slug = str(profile_data.get("theorg_team_slug") or "").replace("-", " ").strip()
    if team_slug:
        keywords.append(team_slug)

    relationship = str(profile_data.get("theorg_relationship") or "").strip()
    if relationship:
        keywords.append(relationship.replace("_", " "))

    if bucket == "recruiters":
        keywords.extend(["talent acquisition", "recruiting", "early careers"])
    elif bucket == "hiring_managers":
        keywords.extend(["engineering", "software", "platform"])

    ordered: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        normalized = _normalize_identity(keyword)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(keyword)
    return ordered[:3]


def _choose_linkedin_backfill_match(
    candidate: dict,
    matches: list[dict],
    *,
    company_name: str,
    bucket: str,
) -> tuple[dict | None, int | None, str]:
    scored_matches: list[tuple[int, int, dict]] = []
    for match in matches:
        name_score = _name_match_score(candidate.get("full_name"), match.get("full_name"))
        if name_score < 90:
            continue
        if not _linkedin_company_match(match, company_name):
            continue
        if not _linkedin_role_match(match, bucket=bucket):
            continue
        title_score = _linkedin_title_match_score(
            candidate,
            match,
            company_name=company_name,
            bucket=bucket,
        )
        scored_matches.append((name_score, title_score, match))

    if not scored_matches:
        return None, None, "no_match"

    scored_matches.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            _normalize_identity(item[2].get("full_name")),
        )
    )
    best_score, best_title_score, best_match = scored_matches[0]
    if len(scored_matches) > 1:
        second_score, second_title_score, _ = scored_matches[1]
        if best_score == second_score:
            if best_title_score == second_title_score:
                return None, None, "ambiguous"
            if best_title_score < 4 and second_title_score >= best_title_score - 1:
                return None, None, "ambiguous"
        elif best_score < 100 and second_score >= best_score - 4 and second_title_score >= best_title_score:
            return None, None, "ambiguous"
    return best_match, best_score, "matched"


async def _backfill_linkedin_profiles(
    candidates: list[dict],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None,
    bucket: str,
    context: JobContext | None = None,
    geo_terms: list[str] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    indexed_candidates = list(enumerate(candidates))

    def _priority(item: tuple[int, dict]) -> tuple[int, int, str]:
        _, candidate = item
        source = str(candidate.get("source") or "")
        trusted_public = _trusted_public_match(candidate, company_name, public_identity_slugs)
        geo_rank = _location_match_rank(candidate, context=context)
        missing_linkedin = not bool(candidate.get("linkedin_url"))
        public_boost = source in PUBLIC_WEB_SOURCES or bool(_public_profile_url(candidate))
        return (
            0 if missing_linkedin and trusted_public and geo_rank == 0 and public_boost else 1,
            0 if geo_rank == 0 else 1,
            _normalize_identity(candidate.get("full_name")),
        )

    async def _backfill_one(index: int, raw: dict) -> tuple[int, dict]:
        data = dict(raw)
        if data.get("linkedin_url"):
            return index, data

        public_url = _public_profile_url(data)
        if not public_url:
            return index, data

        employment_status = data.get("_employment_status") or _classify_employment_status(
            data,
            company_name,
            public_identity_slugs,
        )
        trusted_public = _trusted_public_match(data, company_name, public_identity_slugs)
        if employment_status != "current" and not trusted_public:
            data["profile_data"] = _linkedin_backfill_metadata(data, status="skipped")
            return index, data

        backfill_strategy = "exact_query"
        exact_title_hints = _linkedin_backfill_search_titles(
            data,
            bucket=bucket,
            company_name=company_name,
        )
        exact_name_variants = (
            _linkedin_backfill_name_variants(data.get("full_name"))
            if bucket in {"recruiters", "hiring_managers"}
            else []
        )
        exact_team_keywords = _linkedin_backfill_team_keywords(
            data,
            bucket=bucket,
        )
        exact_geo_terms = geo_terms if _location_match_rank(data, context=context) == 0 else None
        matches = await search_router_client.search_exact_linkedin_profile(
            data.get("full_name", ""),
            company_name,
            name_variants=exact_name_variants,
            title_hints=exact_title_hints,
            team_keywords=exact_team_keywords,
            geo_terms=exact_geo_terms,
            limit=5,
            search_profile=search_profile,
        )
        chosen, confidence, status = _choose_linkedin_backfill_match(
            data,
            matches,
            company_name=company_name,
            bucket=bucket,
        )
        if not chosen and bucket in {"recruiters", "hiring_managers"}:
            broad_titles = exact_title_hints
            if broad_titles:
                broader_matches = await search_router_client.search_people(
                    company_name,
                    titles=broad_titles,
                    team_keywords=None,
                    geo_terms=exact_geo_terms,
                    limit=8,
                    min_results=1,
                    search_profile=search_profile,
                )
                chosen, confidence, broad_status = _choose_linkedin_backfill_match(
                    data,
                    broader_matches,
                    company_name=company_name,
                    bucket=bucket,
                )
                if chosen:
                    matches = broader_matches
                    status = broad_status
                    backfill_strategy = "broad_company_title_query"
        data["profile_data"] = _linkedin_backfill_metadata(
            data,
            status=status,
            confidence=confidence,
            source=chosen.get("source", "search_router") if chosen else "search_router",
            strategy=backfill_strategy,
        )
        if chosen:
            data["linkedin_url"] = chosen.get("linkedin_url", "")
            recovered_title = chosen.get("title", "")
            if recovered_title and (
                bucket != "peer"
                or data.get("_weak_title")
                or _title_is_weak(data.get("title"), company_name)
            ):
                if not _title_is_weak(recovered_title, company_name):
                    data["title"] = recovered_title
                    data["_weak_title"] = False
                    profile_data = _title_recovery_metadata(
                        data,
                        source="linkedin_backfill",
                        confidence=confidence,
                    )
                    profile_data.update(data.get("profile_data") or {})
                    data["profile_data"] = profile_data
        return index, data

    if not indexed_candidates:
        return []

    semaphore = asyncio.Semaphore(3)

    async def _run_backfill(index: int, raw: dict) -> tuple[int, dict]:
        async with semaphore:
            return await _backfill_one(index, raw)

    prioritized = sorted(indexed_candidates, key=_priority)
    processed = await asyncio.gather(*(_run_backfill(index, raw) for index, raw in prioritized))
    processed.sort(key=lambda item: item[0])
    return [item for _, item in processed]


def _prioritize_titles_for_search(
    titles: list[str],
    *,
    bucket: str,
    context: JobContext | None,
) -> list[str]:
    normalized_titles = list(dict.fromkeys(title for title in titles if title))
    if not normalized_titles:
        return []

    def rank(title: str) -> tuple[int, str]:
        normalized = _normalize_identity(title)
        if bucket == "recruiters" and context and context.early_career:
            preferred_order = {
                "campus recruiter": 0,
                "university recruiter": 1,
                "early careers recruiter": 2,
                "early talent recruiter": 3,
                "university programs recruiter": 4,
                "recruiting coordinator": 5,
                "technical sourcer": 6,
                "talent acquisition partner": 7,
                "engineering recruiter": 8,
                "technical recruiter": 9,
                "talent acquisition": 10,
                "recruiter": 11,
            }
            return (preferred_order.get(normalized, 20), normalized)

        if bucket == "hiring_managers" and context and context.early_career and context.department == "engineering":
            preferred_order = {
                "engineering manager": 0,
                "software engineering manager": 1,
                "team lead": 2,
                "tech lead": 3,
                "technical lead": 4,
                "software engineer team lead": 5,
                "software engineer tech lead": 6,
                "software engineering lead": 7,
            }
            return (preferred_order.get(normalized, 20), normalized)

        return (10, normalized)

    return [title for _, title in sorted((rank(title), title) for title in normalized_titles)]


def _broaden_peer_titles_for_retry(context: JobContext | None) -> list[str]:
    if not context:
        return []

    prioritized = _prioritize_titles_for_search(
        context.peer_titles,
        bucket="peers",
        context=context,
    )
    base_titles: list[str] = []
    ml_family_context = (
        "ml" in context.team_keywords
        or any(
            term in _normalize_identity(title)
            for title in prioritized
            for term in (
                "machine learning",
                "ml engineer",
                "applied scientist",
                "data scientist",
                "model training",
                "research engineer",
            )
        )
    )
    if context.department == "data_science" or ml_family_context:
        if "ml" in context.team_keywords or any(
            term in _normalize_identity(title)
            for title in prioritized
            for term in ("machine learning", "ml engineer", "applied scientist", "data scientist", "model training")
        ):
            base_titles.extend(
                [
                    "Machine Learning Engineer",
                    "Software Engineer",
                    "Applied Scientist",
                    "Research Engineer",
                    "Data Scientist",
                    "Model Training Engineer",
                    "Training Infrastructure Engineer",
                    "Distributed Systems Engineer",
                ]
            )
        else:
            base_titles.extend(["Data Scientist", "Research Engineer", "Software Engineer"])
    elif context.department == "engineering":
        engineering_family = ["Software Engineer", "Software Developer"]
        if any(keyword in context.team_keywords for keyword in ("backend", "platform", "cloud", "devops")):
            engineering_family = [
                "Backend Engineer",
                "Platform Engineer",
                "Infrastructure Engineer",
                "Distributed Systems Engineer",
                *engineering_family,
            ]
        if any(keyword in context.team_keywords for keyword in ("frontend", "mobile")):
            engineering_family = [
                "Frontend Engineer",
                "UI Engineer",
                "Mobile Engineer",
                *engineering_family,
            ]
        base_titles.extend(engineering_family)
    elif context.department == "product_management":
        base_titles.extend(["Product Manager", "Technical Program Manager", "Program Manager"])
    elif context.department == "design":
        base_titles.extend(["Product Designer", "UX Designer", "UI Designer"])
    elif context.department == "information_technology":
        base_titles.extend(["Security Engineer", "IT Engineer", "Systems Engineer", "Network Engineer"])
    else:
        dept_label = context.department.replace("_", " ").title()
        base_titles.extend([f"{dept_label} Specialist", f"{dept_label} Analyst"])

    same_level_titles: list[str] = []
    adjacent_titles: list[str] = []
    seen: set[str] = set()
    for title in base_titles + prioritized:
        same_level_variants, adjacent_variants = _peer_title_variants_for_seniority(
            title,
            context.seniority,
        )
        for variant in same_level_variants + adjacent_variants:
            normalized = _normalize_identity(variant)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            if variant in same_level_variants:
                same_level_titles.append(variant)
            else:
                adjacent_titles.append(variant)
    return same_level_titles + adjacent_titles


def _companywide_recruiter_titles(context: JobContext | None) -> list[str]:
    if context:
        titles = _prioritize_titles_for_search(
            context.recruiter_titles
            + [
                "Technical Recruiter",
                "Engineering Recruiter",
                "Talent Acquisition Partner",
                "Technical Sourcer",
                "Recruiting Coordinator",
                "Recruitment Coordinator",
                "Talent Operations",
                "Early Career Programs",
                "Recruiter",
                "University Recruiter",
                "Campus Recruiter",
                "Emerging Talent Recruiter",
                "Early Career Recruiter",
            ],
            bucket="recruiters",
            context=context,
        )
    else:
        titles = [
            "Technical Recruiter",
            "Engineering Recruiter",
            "Talent Acquisition Partner",
            "Technical Sourcer",
            "Recruiting Coordinator",
            "Recruitment Coordinator",
            "Talent Operations",
            "Early Career Programs",
            "Recruiter",
            "University Recruiter",
            "Campus Recruiter",
            "Emerging Talent Recruiter",
            "Early Career Recruiter",
        ]
    return list(dict.fromkeys(title for title in titles if title))


def _companywide_manager_titles(context: JobContext | None) -> list[str]:
    if context:
        titles = _prioritize_titles_for_search(
            context.manager_titles
            + [
                "Engineering Manager",
                "Software Engineering Manager",
                "Technical Lead",
                "Team Lead",
            ],
            bucket="hiring_managers",
            context=context,
        )
    else:
        titles = ["Engineering Manager", "Software Engineering Manager", "Technical Lead", "Team Lead"]
    return list(dict.fromkeys(title for title in titles if title))


def _initial_manager_titles(context: JobContext | None) -> list[str]:
    context_manager_titles = _manager_context_search_titles(context)
    if context:
        titles = _prioritize_titles_for_search(
            context_manager_titles
            + [
                "Engineering Manager",
                "Software Engineering Manager",
                "Software Development Manager",
                "Team Lead",
                "Tech Lead",
                "Technical Lead",
                "Software Engineering Lead",
                "Senior Engineering Manager",
                "Group Engineering Manager",
                "Director of Engineering",
                "Head of Engineering",
            ],
            bucket="hiring_managers",
            context=context,
        )
    else:
        titles = [
            "Engineering Manager",
            "Software Engineering Manager",
            "Software Development Manager",
            "Team Lead",
            "Tech Lead",
            "Technical Lead",
            "Software Engineering Lead",
            "Senior Engineering Manager",
            "Group Engineering Manager",
            "Director of Engineering",
            "Head of Engineering",
        ]
    return list(dict.fromkeys(title for title in titles if title))


def _manager_geo_recovery_titles(context: JobContext | None) -> list[str]:
    base_titles = _initial_manager_titles(context)
    expanded = base_titles + [
        "Senior Engineering Manager",
        "Group Engineering Manager",
        "Director of Engineering",
        "Head of Engineering",
        "VP Engineering",
        "Engineering Leader",
    ]
    return list(dict.fromkeys(title for title in expanded if title))


def _manager_geo_recovery_keywords(context: JobContext | None) -> list[str]:
    keywords = ["engineering leader", "engineering leadership"]
    if context:
        keywords.extend(context.product_team_names[:1])
        keywords.extend(context.team_keywords[:2])
        keywords.extend(["engineering", "software"])
    return list(dict.fromkeys(keyword for keyword in keywords if keyword))


def _recruiter_targeted_recovery_titles(context: JobContext | None) -> list[str]:
    base_titles = _companywide_recruiter_titles(context)
    expanded = base_titles + [
        "Talent Acquisition Manager",
        "Talent Acquisition Leader",
        "Senior Talent Acquisition Manager",
        "Head of Talent Acquisition",
        "University Recruitment",
    ]
    return list(dict.fromkeys(title for title in expanded if title))


def _recruiter_targeted_recovery_keywords(context: JobContext | None) -> list[str]:
    keywords = ["recruiter", "talent acquisition", "hiring"]
    if context and context.early_career:
        keywords.extend(["university recruitment", "campus recruiting", "early careers"])
    if context and context.department == "engineering":
        keywords.extend(["technical recruiting", "engineering hiring"])
    return list(dict.fromkeys(keyword for keyword in keywords if keyword))


def _peer_targeted_recovery_titles(context: JobContext | None) -> list[str]:
    if context and context.department == "engineering":
        titles = [
            "Software Engineer",
            "Software Developer",
            "Full Stack Software Developer",
            "Full Stack Engineer",
        ]
        if any(keyword in context.team_keywords for keyword in ("qa", "quality assurance", "test")):
            titles.extend(["QA Engineer", "Quality Assurance Engineer", "Software Development Engineer in Test"])
        if any(keyword in context.team_keywords for keyword in ("frontend", "ui", "web")):
            titles.extend(["Frontend Engineer", "UI Engineer"])
        if any(keyword in context.team_keywords for keyword in ("backend", "platform", "infrastructure")):
            titles.extend(["Backend Engineer", "Platform Engineer"])
        return list(dict.fromkeys(title for title in titles if title))
    return _companywide_peer_titles(context)


def _peer_targeted_recovery_keywords(context: JobContext | None) -> list[str]:
    keywords: list[str] = []
    if context:
        keywords.extend(context.team_keywords[:2])
        keywords.extend(context.product_team_names[:1])
    keywords.extend(["software engineer", "software developer"])
    return list(dict.fromkeys(keyword for keyword in keywords if keyword))


def _manager_context_search_titles(context: JobContext | None) -> list[str]:
    if not context:
        return []
    filtered: list[str] = []
    for title in context.manager_titles:
        normalized = _normalize_identity(title)
        if not normalized:
            continue
        if not any(
            marker in normalized
            for marker in ("manager", "director", "head", "vice president", "vp")
        ):
            continue
        filtered.append(title)
    return list(dict.fromkeys(filtered))


def _sanitize_search_keywords(keywords: list[str], *, company_name: str) -> list[str]:
    sanitized: list[str] = []
    company_tokens = {
        _normalize_identity(company_name),
        _normalize_identity(company_name.replace("&", "and")),
    }
    for keyword in keywords:
        normalized = _normalize_identity(keyword)
        if not normalized or normalized in company_tokens:
            continue
        if normalized in {"company", "team", "role", "job"}:
            continue
        sanitized.append(keyword)
    return list(dict.fromkeys(sanitized))


def _has_recruiter_lead_candidate(candidates: list[dict]) -> bool:
    for candidate in candidates:
        haystack = " ".join(
            part for part in [candidate.get("title", ""), candidate.get("snippet", ""), candidate.get("location", "")]
            if part
        ).lower()
        if not _is_recruiter_like(haystack):
            continue
        if any(keyword in haystack for keyword in ("lead", "head", "manager", "director", "canada", "university recruitment")):
            return True
    return False


def _should_run_recruiter_targeted_recovery(
    candidates: list[dict],
    *,
    context: JobContext | None,
    target_count_per_bucket: int,
) -> bool:
    return (
        _needs_more_bucket_size_only(candidates, target_count_per_bucket=target_count_per_bucket)
        or not _has_local_geo_match(candidates, context=context)
        or not _has_recruiter_lead_candidate(candidates)
    )


def _should_run_peer_targeted_recovery(
    candidates: list[dict],
    *,
    context: JobContext | None,
    target_count_per_bucket: int,
) -> bool:
    return _needs_more_bucket_size_only(
        candidates,
        target_count_per_bucket=target_count_per_bucket,
    ) or not _has_local_geo_match(candidates, context=context)


def _companywide_peer_titles(context: JobContext | None, fallback_titles: list[str] | None = None) -> list[str]:
    if context:
        titles = _broaden_peer_titles_for_retry(context)
    else:
        titles = fallback_titles or ["Software Engineer", "Backend Engineer", "Platform Engineer", "Developer"]
    return list(dict.fromkeys(title for title in titles if title))


async def _expand_peer_candidates(
    company_name: str,
    existing_candidates: list[dict],
    *,
    context: JobContext | None,
    public_identity_terms: list[str] | None,
    geo_terms: list[str] | None = None,
    company_domain: str | None = None,
    limit: int,
    min_results: int,
    debug_bucket: dict[str, Any] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    if not context:
        return existing_candidates
    if len(existing_candidates) >= min_results:
        return existing_candidates

    retry_titles = _broaden_peer_titles_for_retry(context)
    if not retry_titles:
        return existing_candidates

    retry_candidates = await _search_candidates(
        company_name,
        titles=retry_titles,
        departments=context.apollo_departments,
        team_keywords=None,
        geo_terms=geo_terms,
        public_identity_terms=public_identity_terms,
        company_domain=company_domain,
        limit=limit,
        min_results=max(1, min_results),
        debug_bucket=debug_bucket,
        search_profile=search_profile,
    )
    return _dedupe_candidates(existing_candidates, retry_candidates)


def _public_url_matches_company(public_url: str, company_name: str) -> bool:
    if not public_url:
        return False
    return _slugify(company_name) in urlparse(public_url).path.lower()


def _trusted_public_match(data: dict, company_name: str, public_identity_slugs: list[str] | None = None) -> bool:
    public_url = _public_profile_url(data)
    return matches_public_company_identity(public_url, company_name, public_identity_slugs)


def _trusted_public_peer_match(
    data: dict,
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
    context: JobContext | None = None,
) -> bool:
    if _trusted_public_match(data, company_name, public_identity_slugs):
        return True
    if not _is_linkedin_public_profile(data):
        return False

    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    linkedin_result_title = ((data.get("profile_data") or {}).get("linkedin_result_title", "") or "")
    location = data.get("location", "") or ((data.get("profile_data") or {}).get("location", "") or "")
    haystack = " ".join(part for part in [title, snippet, linkedin_result_title, location] if part)
    if not _mentions_company(haystack, company_name):
        return False
    employment_status = _classify_employment_status(data, company_name, public_identity_slugs)
    if employment_status == "former":
        return False
    if not (_role_like_title(title) or _role_like_title(snippet)):
        return False
    if context and context.job_locations:
        return _location_match_rank(data, context=context) == 0 or _candidate_geo_signal_match(data, context=context)
    return True


def _candidate_matches_company(
    data: dict,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> bool:
    source = data.get("source", "")
    if source in CURRENT_TRUSTED_SOURCES:
        return True

    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    # The LinkedIn result parser strips "@ Company" from the title for clean
    # display, but the original search result title still holds the company
    # reference.  Check it so that "Emerging Talent Recruiter @ Meta" still
    # matches even though the cleaned title is "Emerging Talent Recruiter".
    linkedin_result_title = (
        (data.get("profile_data") or {}).get("linkedin_result_title", "")
    )
    public_url = _public_profile_url(data)
    host = _public_profile_host(data)
    company_mentioned = (
        _mentions_company(title, company_name)
        or _mentions_company(snippet, company_name)
        or _mentions_company(linkedin_result_title, company_name)
        or _trusted_public_match(data, company_name, public_identity_slugs)
        or (
            not is_ambiguous_company_name(company_name)
            and _public_url_matches_company(public_url, company_name)
        )
    )

    if host in CURRENT_TRUSTED_PUBLIC_HOSTS and not _trusted_public_match(
        data,
        company_name,
        public_identity_slugs,
    ):
        return False

    if title and not _role_like_title(title) and not _mentions_company(title, company_name):
        return False

    combined_text = " ".join(part for part in [title, snippet] if part).lower()
    if data.get("source") in PUBLIC_WEB_SOURCES and any(term in combined_text for term in PUBLIC_DIRECTORY_TERMS):
        return False

    return company_mentioned


def _classify_employment_status(
    data: dict,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> str:
    source = data.get("source", "")
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    host = _public_profile_host(data)
    haystack = " ".join(part for part in [title, snippet] if part).lower()

    if _mentions_company(haystack, company_name) and any(
        re.search(pattern, haystack) for pattern in FORMER_COMPANY_PATTERNS
    ):
        return "former"

    if source in CURRENT_TRUSTED_SOURCES:
        return "current"

    if host in CURRENT_TRUSTED_PUBLIC_HOSTS and _trusted_public_match(
        data,
        company_name,
        public_identity_slugs,
    ):
        return "current"

    current_company_patterns = (
        rf"\bcurrently\b.*\b{re.escape(company_name.lower())}\b",
        rf"\bcurrent\b.*\b{re.escape(company_name.lower())}\b",
        rf"\bworks?\s+at\b.*\b{re.escape(company_name.lower())}\b",
        rf"\bworking\s+at\b.*\b{re.escape(company_name.lower())}\b",
    )
    if any(re.search(pattern, haystack) for pattern in current_company_patterns):
        return "current"

    if _is_linkedin_public_profile(data):
        strong_public_profile_patterns = (
            rf"\babout\b.*\bi\s+(?:lead|manage|work|support)\b.*\b{re.escape(company_name.lower())}\b",
            r"\babout\b.*\bresponsible for hiring\b.*\b(?:canada|toronto|greater toronto area|gta)\b",
            rf"\bexperience\b.*\b{re.escape(company_name.lower())}\b",
        )
        if any(re.search(pattern, haystack) for pattern in strong_public_profile_patterns):
            return "current"

    if _mentions_company(title, company_name):
        return "current"

    # The LinkedIn parser strips "@ Company" from the display title, but the
    # original search result title retains it.  Use it for employment signal.
    linkedin_result_title = (
        (data.get("profile_data") or {}).get("linkedin_result_title", "")
    )
    if linkedin_result_title and _mentions_company(linkedin_result_title, company_name):
        return "current"

    if _mentions_company(snippet, company_name):
        return "ambiguous"

    return "ambiguous"


def _classify_org_level(title: str, source: str = "", snippet: str = "") -> str:
    haystack = " ".join(part for part in [title, snippet, source] if part).lower()
    if any(keyword in haystack for keyword in DIRECTOR_PLUS_KEYWORDS):
        return "director_plus"
    # IC manager titles (Product Manager, Program Manager, etc.) are ICs
    # unless they carry a senior leadership prefix.
    if _is_ic_manager_title(haystack):
        title_lower = (title or "").lower()
        if _SENIOR_LEADERSHIP_PREFIXES.search(title_lower):
            return "manager"
        return "ic"
    if any(keyword in haystack for keyword in MANAGER_TITLE_KEYWORDS):
        return "manager"
    if any(keyword in haystack for keyword in CONTROLLED_LEAD_KEYWORDS):
        return "manager"
    return "ic"


def _recruiter_scope_rank_from_text(*parts: str) -> int:
    haystack = " ".join(part for part in parts if part).lower()
    if not haystack:
        return 3
    if re.search(
        r"\b(?:lead|head|manager|director|principal)\b[^.;\n]{0,40}\b(?:talent acquisition|recruit(?:er|ing|ment)|sourc(?:er|ing))\b",
        haystack,
    ) or "responsible for hiring in canada" in haystack or "hiring in canada and the us" in haystack:
        return 0
    if re.search(r"\b(?:senior|staff|partner)\b[^.;\n]{0,40}\b(?:recruit(?:er|ing)|talent acquisition|sourc(?:er|ing))\b", haystack):
        return 1
    if _is_recruiter_like(haystack):
        return 2
    return 3


def _source_rank(source: str | None) -> int:
    return SOURCE_PRIORITY.get(source or "", 5)


def _org_rank(bucket: str, org_level: str) -> int:
    if bucket == "hiring_managers":
        return {"manager": 0, "director_plus": 1, "ic": 2}.get(org_level, 3)
    if bucket == "recruiters":
        return 0
    return {"ic": 0, "manager": 1, "director_plus": 2}.get(org_level, 3)


def _context_rank(data: dict, context: JobContext | None) -> int:
    if not context:
        return 1
    haystack = " ".join(
        part for part in [
            data.get("title", ""),
            data.get("snippet", ""),
            data.get("department", ""),
        ] if part
    ).lower()
    for keyword in context.team_keywords + context.domain_keywords:
        if _keyword_in_text(keyword, haystack):
            return 0
    if context.department.replace("_", " ") in haystack:
        return 0
    return 1


def _team_keyword_match_rank(data: dict, *, bucket: str, context: JobContext | None) -> int:
    """Rank how well the candidate's title matches team keywords (lower=better).

    For hiring managers at large orgs, this is the critical differentiator:
    a 'Backend Engineering Manager' should rank above a generic 'Engineering Manager'
    when the job is a backend role.
    """
    if not context or not context.team_keywords:
        return 1
    title_lower = (data.get("title", "") or "").lower()
    if not title_lower:
        return 2
    hits = sum(1 for kw in context.team_keywords if _keyword_in_text(kw, title_lower))
    if hits >= 2:
        return 0
    if hits == 1:
        return 0
    dept_label = context.department.replace("_", " ")
    if dept_label in title_lower:
        return 1
    return 2


def _peer_title_alignment_rank(data: dict, *, context: JobContext | None) -> int:
    if not context:
        return 1
    title = (data.get("title", "") or "").lower()
    snippet = (data.get("snippet", "") or "").lower()
    haystack = " ".join(part for part in [title, snippet] if part)
    if not haystack:
        return 2

    if context.department == "engineering":
        direct_terms = (
            "full stack",
            "fullstack",
            "software engineer",
            "software developer",
            "backend engineer",
            "frontend engineer",
            "ui engineer",
            "platform engineer",
            "web engineer",
        )
        adjacent_terms = (
            "engineer",
            "developer",
        )
        off_target_terms = (
            "machine learning",
            "applied scientist",
            "data scientist",
            "security engineer",
            "site reliability",
            "sre",
        )
        if any(term in haystack for term in direct_terms):
            return 0
        if any(term in haystack for term in off_target_terms):
            return 2
        if any(term in haystack for term in adjacent_terms):
            return 1
        return 2
    return 1


def _location_match_rank(data: dict, *, context: JobContext | None) -> int:
    """Return 0 if candidate location overlaps a job location, else 1.

    Location data may come from Apollo, SERP snippets, or profile_data.
    We do fuzzy city/metro matching: "San Francisco, CA" matches
    "San Francisco" or "SF Bay Area".
    """
    if not context or not context.job_locations:
        return 1  # neutral — no job location to compare
    candidate_location = (
        data.get("city")
        or data.get("location")
        or (data.get("profile_data") or {}).get("location")
        or ""
    ).lower()
    if not candidate_location:
        return 1  # unknown location — neutral
    for job_loc in context.job_locations:
        job_loc_lower = job_loc.lower()
        # Direct substring match (handles "San Francisco" in "San Francisco, CA")
        if job_loc_lower in candidate_location or candidate_location in job_loc_lower:
            return 0
        # City-level match: extract city part and compare
        job_city = job_loc_lower.split(",")[0].strip()
        candidate_city = candidate_location.split(",")[0].strip()
        if job_city and candidate_city and (job_city in candidate_city or candidate_city in job_city):
            return 0
    return 1


def _recency_rank(data: dict) -> int:
    """Return 0 for recently-discovered/fresh candidates, 1 otherwise.

    Uses Apollo employment start date, cache freshness, or discovery
    recency as signals.
    """
    profile_data = data.get("profile_data") or {}

    # Signal 1: Known people cache freshness
    if profile_data.get("cache_freshness") == "fresh":
        return 0

    # Signal 2: Apollo employment start date (recent = better for peers)
    start_date = data.get("employment_start_date") or profile_data.get("employment_start_date")
    if start_date:
        try:
            start = datetime.fromisoformat(str(start_date).replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - start).days
            if age_days <= 730:  # joined within last 2 years
                return 0
        except (ValueError, TypeError):
            pass

    return 1


def _candidate_sort_key(data: dict, *, bucket: str, context: JobContext | None) -> tuple:
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    location_rank = _location_match_rank(data, context=context)
    context_rank = _context_rank(data, context)
    org_rank = _org_rank(bucket, data.get("_org_level", "ic"))
    source_rank = _source_rank(data.get("source"))
    seniority_rank = _seniority_fit_rank(data, bucket=bucket, context=context)
    weak_title_rank = 1 if data.get("_weak_title") else 0
    role_title_rank = 0 if _role_like_title(title) else 1
    normalized_name = _normalize_identity(data.get("full_name"))
    if bucket == "recruiters":
        explicit_role_rank = 0 if _is_recruiter_like(title) else 1 if _is_recruiter_like(snippet) else 2
        recruiter_scope_rank = _recruiter_scope_rank_from_text(
            title,
            snippet,
            str(profile_data.get("linkedin_result_title") or ""),
            str(profile_data.get("public_snippet") or ""),
        )
        return (
            0 if data.get("_actively_hiring") else 1,
            recruiter_scope_rank,
            location_rank,
            context_rank,
            explicit_role_rank,
            org_rank,
            source_rank,
            seniority_rank,
            weak_title_rank,
            role_title_rank,
            normalized_name,
        )
    if bucket == "hiring_managers":
        manager_keywords = MANAGER_TITLE_KEYWORDS + CONTROLLED_LEAD_KEYWORDS
        explicit_role_rank = 0 if _contains_any_keyword(title, manager_keywords) else 1 if _contains_any_keyword(snippet, manager_keywords) else 2
        return (
            0 if data.get("_actively_hiring") else 1,
            _team_keyword_match_rank(data, bucket=bucket, context=context),
            location_rank,
            context_rank,
            org_rank,
            source_rank,
            seniority_rank,
            explicit_role_rank,
            weak_title_rank,
            role_title_rank,
            normalized_name,
        )
    return (
        org_rank,
        0 if data.get("_actively_hiring") else 1,
        _peer_title_alignment_rank(data, context=context),
        location_rank,
        context_rank,
        source_rank,
        seniority_rank,
        _recency_rank(data) if bucket == "peers" else 0,
        weak_title_rank,
        role_title_rank,
        normalized_name,
    )


def _allow_director_plus(context: JobContext | None) -> bool:
    return bool(context and context.seniority in SENIOR_MANAGER_LEVELS)


def _manager_seniority_filters(context: JobContext | None) -> list[str]:
    if context and getattr(context, "early_career", False):
        return ["manager"]
    if context and context.seniority in {"intern", "junior"}:
        return ["manager"]
    return ["manager", "director", "vp"]


def _peer_seniority_filters(context: JobContext | None) -> list[str] | None:
    """Return Apollo seniority filters for peers, or None if no restriction.

    For early-career / junior roles, restrict peers to entry-level and
    mid-level so we don't surface Directors as "peers".
    For senior+ roles, allow broader range (no filter).
    """
    if not context:
        return None
    if context.early_career or context.seniority in {"intern", "junior"}:
        return ["entry", "junior", "mid"]
    if context.seniority in {"mid"}:
        return ["junior", "mid", "senior"]
    return None  # senior+ jobs: no restriction


def _prepare_candidates(
    candidates: list[dict],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
    bucket: str,
    context: JobContext | None,
    limit: int,
    debug_funnel: dict[str, Any] | None = None,
) -> list[dict]:
    expected_type = {
        "recruiters": "recruiter",
        "hiring_managers": "hiring_manager",
        "peers": "peer",
    }[bucket]

    current_primary: list[dict] = []
    ambiguous_primary: list[dict] = []
    current_fallback: list[dict] = []
    ambiguous_fallback: list[dict] = []
    decisions: list[dict[str, Any]] = []

    for raw in candidates:
        data = dict(raw)
        decision = _debug_candidate_summary(data)
        title = data.get("title", "") or ""
        snippet = data.get("snippet", "") or ""
        weak_title = data.get("_weak_title")
        if weak_title is None:
            weak_title = _title_is_weak(title, company_name)
            data["_weak_title"] = weak_title
        if bucket in {"recruiters", "hiring_managers"} and weak_title:
            # For ambiguous companies, weak titles from broad search may still
            # be real employees — include as low-priority fallbacks in peers bucket
            # instead of silently dropping them
            decision["status"] = "excluded"
            decision["reason"] = "weak_title"
            decisions.append(decision)
            continue
        if not _candidate_matches_company(data, company_name, public_identity_slugs):
            decision["status"] = "excluded"
            decision["reason"] = "company_mismatch"
            decisions.append(decision)
            continue
        if (
            bucket == "peers"
            and data.get("source") in PUBLIC_WEB_SOURCES
            and not _trusted_public_peer_match(
                data,
                company_name=company_name,
                public_identity_slugs=public_identity_slugs,
                context=context,
            )
        ):
            decision["status"] = "excluded"
            decision["reason"] = "untrusted_public_peer_candidate"
            decisions.append(decision)
            continue

        person_type = _classify_person(
            title,
            source=data.get("source", ""),
            snippet=snippet,
        )
        senior_ic_fallback = False
        if person_type != expected_type:
            if bucket == "hiring_managers" and person_type == "peer" and _is_senior_ic_fallback(title):
                senior_ic_fallback = True
            else:
                decision["status"] = "excluded"
                decision["reason"] = f"bucket_type_mismatch:{person_type}"
                decisions.append(decision)
                continue
        if bucket == "recruiters":
            if not (
                _is_recruiter_like(title)
                or _is_recruiter_like(snippet)
            ):
                decision["status"] = "excluded"
                decision["reason"] = "not_recruiter_like"
                decisions.append(decision)
                continue
            if title and not (
                _is_recruiter_like(title)
                or _role_like_title(title)
            ):
                decision["status"] = "excluded"
                decision["reason"] = "recruiter_title_not_role_like"
                decisions.append(decision)
                continue
        if bucket == "hiring_managers" and title and not (
            _is_manager_like(title)
            or _role_like_title(title)
        ):
            decision["status"] = "excluded"
            decision["reason"] = "not_manager_like"
            decisions.append(decision)
            continue
        if bucket == "hiring_managers" and _generic_manager_title(title) and not _manager_candidate_has_engineering_context(
            data,
            context=context,
        ):
            decision["status"] = "excluded"
            decision["reason"] = "generic_manager_without_engineering_context"
            decisions.append(decision)
            continue

        employment_status = _classify_employment_status(data, company_name, public_identity_slugs)
        if employment_status == "former":
            decision["status"] = "excluded"
            decision["reason"] = "former_employee"
            decisions.append(decision)
            continue

        org_level = _classify_org_level(
            data.get("title", ""),
            source=data.get("source", ""),
            snippet=data.get("snippet", ""),
        )

        if bucket == "hiring_managers" and org_level == "ic" and not senior_ic_fallback:
            decision["status"] = "excluded"
            decision["reason"] = "ic_manager_bucket_excluded"
            decisions.append(decision)
            continue
        if bucket == "peers" and org_level == "director_plus":
            decision["status"] = "excluded"
            decision["reason"] = "director_plus_peer_excluded"
            decisions.append(decision)
            continue

        is_fallback = False
        if (
            bucket == "hiring_managers"
            and org_level == "director_plus"
            and not _allow_director_plus(context)
            and _location_match_rank(data, context=context) != 0
        ):
            is_fallback = True
        if bucket == "recruiters" and org_level == "director_plus" and _location_match_rank(data, context=context) != 0:
            is_fallback = True
        if senior_ic_fallback:
            is_fallback = True

        data["_employment_status"] = employment_status
        data["_org_level"] = org_level
        data["_director_fallback"] = is_fallback
        data["_senior_ic_fallback"] = senior_ic_fallback

        group_name = "current_primary"
        if employment_status == "current":
            if is_fallback:
                group_name = "current_fallback"
                current_fallback.append(data)
            else:
                current_primary.append(data)
        else:
            if is_fallback:
                group_name = "ambiguous_fallback"
                ambiguous_fallback.append(data)
            else:
                group_name = "ambiguous_primary"
                ambiguous_primary.append(data)
        data["_debug_group"] = group_name
        decision["status"] = "included"
        decision["group"] = group_name
        decision["employment_status"] = employment_status
        decision["org_level"] = org_level
        decisions.append(decision)

    current_primary.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))
    ambiguous_primary.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))
    current_fallback.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))
    ambiguous_fallback.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))

    ranked: list[dict] = []
    ranked.extend(current_primary)
    if len(ranked) < limit:
        ranked.extend(ambiguous_primary[: max(0, limit - len(ranked))])
    if len(ranked) < limit:
        ranked.extend(current_fallback[: max(0, limit - len(ranked))])
    if len(ranked) < limit:
        ranked.extend(ambiguous_fallback[: max(0, limit - len(ranked))])
    if debug_funnel is not None:
        debug_funnel["decisions"] = decisions
        debug_funnel["counts"] = {
            "input": len(candidates),
            "current_primary": len(current_primary),
            "ambiguous_primary": len(ambiguous_primary),
            "current_fallback": len(current_fallback),
            "ambiguous_fallback": len(ambiguous_fallback),
            "ranked": len(ranked),
        }
        debug_funnel["ranked"] = [
            {
                **_debug_candidate_summary(item),
                "group": item.get("_debug_group"),
                "sort_key": list(_candidate_sort_key(item, bucket=bucket, context=context)),
                "usefulness_score": _compute_usefulness_score(
                    item,
                    bucket=bucket,
                    context=context,
                    company_name=company_name,
                    public_identity_slugs=public_identity_slugs,
                ),
            }
            for item in ranked[: min(len(ranked), max(limit, 15))]
        ]
    return ranked[:limit]


def _should_expand_with_theorg(
    company_name: str,
    current_counts: dict[str, int],
    *,
    context: JobContext | None = None,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
) -> bool:
    target_count_per_bucket = _clamp_target_count_per_bucket(target_count_per_bucket)
    if is_ambiguous_company_name(company_name):
        return True
    return any(count < target_count_per_bucket for count in current_counts.values())


def _is_ic_manager_title(text: str) -> bool:
    """Check if text contains an IC role with 'manager' in the title.

    Product Manager, Program Manager, etc. are individual-contributor roles
    even though they contain the word 'manager'.
    """
    return any(re.search(p, text) for p in _IC_MANAGER_PATTERNS)


# Prefixes/keywords that promote an IC-manager title to people-manager level.
# "Group Product Manager" or "Director of Product" are people-managers,
# even though the core role (Product Manager) is an IC title.
_SENIOR_LEADERSHIP_PREFIXES = re.compile(
    r"\b(?:group|director|head|vp|vice president|chief|managing)\b",
    re.IGNORECASE,
)


def _classify_person(title: str, source: str = "", snippet: str = "") -> str:
    """Classify a result into recruiter, hiring_manager, or peer."""
    haystack = " ".join(part for part in [title, snippet, source] if part).lower()
    if _is_recruiter_like(haystack):
        return "recruiter"
    # IC manager titles (Product Manager, Program Manager, etc.) are peers
    # UNLESS they carry a senior leadership prefix (Group PM, Director of
    # Product, VP Product, Head of Product).
    if _is_ic_manager_title(haystack):
        title_lower = (title or "").lower()
        if _SENIOR_LEADERSHIP_PREFIXES.search(title_lower):
            return "hiring_manager"
        return "peer"
    if any(keyword in haystack for keyword in MANAGER_TITLE_KEYWORDS):
        return "hiring_manager"
    if any(keyword in haystack for keyword in CONTROLLED_LEAD_KEYWORDS):
        return "hiring_manager"
    return "peer"


def _compute_match_metadata(
    data: dict,
    person_type: str,
    context: JobContext | None = None,
) -> tuple[str, str | None]:
    """Classify a result as direct or next-best and explain why."""
    title = (data.get("title") or "").lower()
    snippet = (data.get("snippet") or "").lower()
    department = (data.get("department") or "").lower()
    haystack = " ".join(part for part in [title, snippet, department] if part)

    if person_type == "peer" and data.get("_weak_title"):
        return "next_best", "Current employment is verified, but the title specificity is weak."
    if person_type == "hiring_manager" and data.get("_senior_ic_fallback"):
        return "next_best", "Senior IC fallback at the target company."

    if person_type == "recruiter":
        if _is_adjacent_recruiter_like(title) or _is_adjacent_recruiter_like(snippet):
            return "adjacent", "Talent-acquisition contact at the target company."
        if context and context.department in {"engineering", "data_science"}:
            return "direct", "Recruiting title aligned to technical hiring."
        return "direct", "Recruiting title at the target company."

    if context:
        for keyword in context.team_keywords + context.domain_keywords:
            if _keyword_in_text(keyword, haystack):
                return "direct", f"Matched {keyword.replace('_', ' ')} context."

        department_label = context.department.replace("_", " ")
        if department_label in haystack:
            return "direct", f"Matched {department_label} context."

        if person_type == "hiring_manager":
            return "adjacent", f"Adjacent {department_label} manager at the target company."
        return "adjacent", f"Adjacent {department_label} teammate at the target company."

    if person_type == "hiring_manager":
        return "direct", "Relevant manager title at the target company."
    if person_type == "peer":
        return "direct", "Relevant teammate title at the target company."
    return "direct", None


def _candidate_bucket_role_fit_rank(bucket: str, data: dict) -> int:
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    if bucket == "recruiters":
        if _is_recruiter_like(title):
            return 0
        if _is_recruiter_like(snippet):
            return 1
        return 2
    if bucket == "hiring_managers":
        if _is_manager_like(title):
            return 0
        if _is_manager_like(snippet):
            return 1
        if data.get("_senior_ic_fallback"):
            return 2
        return 3
    if data.get("_senior_ic_fallback"):
        return 1
    return 0


def _manager_title_specificity_rank(data: dict) -> int:
    title = _normalize_identity(data.get("title"))
    if not title:
        return 5
    if any(keyword in title for keyword in ("software engineering manager", "software development manager", "engineering manager")):
        return 0
    if any(keyword in title for keyword in ("senior engineering manager", "group engineering manager")):
        return 1
    if any(keyword in title for keyword in ("director of engineering", "head of engineering", "vp engineering", "vice president engineering")):
        return 2
    if "leader" in title or any(keyword in title for keyword in CONTROLLED_LEAD_KEYWORDS):
        return 3
    if any(keyword in title for keyword in ("director", "head", "vice president", "vp")):
        return 4
    return 5


def _candidate_bucket_assignment_rank(
    bucket: str,
    data: dict,
    *,
    context: JobContext | None,
    company_name: str = "",
    public_identity_slugs: list[str] | None = None,
) -> tuple[int, int, int, int, int, int, int, str]:
    person_type = {
        "recruiters": "recruiter",
        "hiring_managers": "hiring_manager",
        "peers": "peer",
    }[bucket]
    match_quality, _ = _compute_match_metadata(data, person_type, context)
    usefulness = _compute_usefulness_score(
        data,
        bucket=bucket,
        context=context,
        company_name=company_name,
        public_identity_slugs=public_identity_slugs,
    )
    return (
        _match_rank(match_quality),
        100 - usefulness,  # higher usefulness = lower rank = better
        _candidate_bucket_role_fit_rank(bucket, data),
        _manager_title_specificity_rank(data) if bucket == "hiring_managers" else 0,
        _seniority_fit_rank(data, bucket=bucket, context=context),
        1 if data.get("_director_fallback") or data.get("_senior_ic_fallback") else 0,
        0 if data.get("linkedin_url") else 1,
        _normalize_identity(data.get("full_name")),
    )


def _dedupe_candidate_bucket_groups(
    bucket_groups: dict[str, list[dict]],
    *,
    context: JobContext | None,
    company_name: str = "",
    public_identity_slugs: list[str] | None = None,
) -> dict[str, list[dict]]:
    winners: dict[str, tuple[str, tuple[int, int, int, int, int, int, str]]] = {}
    for bucket, candidates in bucket_groups.items():
        for candidate in candidates:
            key = _candidate_key(candidate)
            rank = _candidate_bucket_assignment_rank(
                bucket,
                candidate,
                context=context,
                company_name=company_name,
                public_identity_slugs=public_identity_slugs,
            )
            current = winners.get(key)
            if current is None or rank < current[1]:
                winners[key] = (bucket, rank)

    return {
        bucket: [
            candidate
            for candidate in candidates
            if winners.get(_candidate_key(candidate), (None, None))[0] == bucket
        ]
        for bucket, candidates in bucket_groups.items()
    }


def _dedupe_candidates(*groups: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for candidate in group:
            key = _candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _balanced_candidate_mix(*groups: list[dict], limit: int) -> list[dict]:
    mixed: list[dict] = []
    seen: set[str] = set()
    index = 0
    active = True
    while active and len(mixed) < limit:
        active = False
        for group in groups:
            if index >= len(group):
                continue
            active = True
            candidate = group[index]
            key = _candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            mixed.append(candidate)
            if len(mixed) >= limit:
                break
        index += 1
    return mixed


def _interactive_enrichment_limit_for_target(target_count_per_bucket: int) -> int:
    return max(4, target_count_per_bucket + 1)


def _limit_interactive_bucket(items: list[T], *, target_count_per_bucket: int) -> list[T]:
    return items[:_interactive_enrichment_limit_for_target(target_count_per_bucket)]


def _has_local_geo_match(candidates: list[dict], *, context: JobContext | None) -> bool:
    return any(_candidate_geo_signal_match(candidate, context=context) for candidate in candidates)


def _should_run_manager_geo_recovery(
    candidates: list[dict],
    *,
    context: JobContext | None,
    target_count_per_bucket: int,
) -> bool:
    return _needs_more_bucket_size_only(
        candidates,
        target_count_per_bucket=target_count_per_bucket,
    ) or not _has_local_geo_match(candidates, context=context)


def _mark_linkedin_backfill_deferred(candidates: list[dict]) -> list[dict]:
    deferred: list[dict] = []
    for raw in candidates:
        candidate = dict(raw)
        profile_data = dict(candidate.get("profile_data") or {})
        if not candidate.get("linkedin_url"):
            profile_data.setdefault("linkedin_backfill_status", "deferred_interactive")
            profile_data.setdefault("linkedin_backfill_strategy", "deferred_after_response")
        candidate["profile_data"] = profile_data
        deferred.append(candidate)
    return deferred


def _record_timing(
    debug: dict[str, Any] | None,
    *,
    stage: str,
    started_at: float,
    **details: Any,
) -> None:
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    logger.warning("people_search_timing stage=%s duration_ms=%.2f details=%s", stage, duration_ms, details)
    if debug is None:
        return
    timings = debug.setdefault("timings", [])
    timings.append(
        {
            "stage": stage,
            "duration_ms": duration_ms,
            **details,
        }
    )


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


async def _search_candidates(
    company_name: str,
    *,
    titles: list[str],
    departments: list[str] | None = None,
    seniority: list[str] | None = None,
    team_keywords: list[str] | None = None,
    geo_terms: list[str] | None = None,
    public_identity_terms: list[str] | None = None,
    company_domain: str | None = None,
    limit: int = 5,
    min_results: int = 2,
    db: AsyncSession | None = None,
    debug_bucket: dict[str, Any] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    """Run Apollo plus routed SERP/public search with dedupe.

    When *db* is provided, checks the global known-people cache first.
    If the cache has enough results, external API calls are skipped.
    """
    # --- Global cache lookup (when db available) ---
    cached_results: list[dict] = []
    if debug_bucket is not None:
        debug_bucket["search_inputs"] = {
            "company_name": company_name,
            "titles": titles,
            "departments": departments,
            "seniority": seniority,
            "team_keywords": team_keywords,
            "geo_terms": geo_terms,
            "public_identity_terms": public_identity_terms,
            "company_domain": company_domain,
            "limit": limit,
            "min_results": min_results,
        }
    if db is not None:
        try:
            from app.services.known_people_service import lookup_known_people
            cached_results = await lookup_known_people(
                db, company_name=company_name, limit=limit,
            )
        except Exception:
            logger.debug("Known people cache lookup failed for %s", company_name, exc_info=True)
            cached_results = []

        if debug_bucket is not None:
            debug_bucket["known_people"] = {
                "count": len(cached_results),
                "cache_hit": len(cached_results) >= min_results,
                "sample_results": [_debug_candidate_summary(item) for item in cached_results[:5]],
            }
        if len(cached_results) >= min_results:
            return cached_results[: max(limit, 8)]

    apollo_filtered = await apollo_client.search_people(
        company_name,
        titles=titles,
        departments=departments,
        seniority=seniority,
        limit=limit,
    )
    apollo_unfiltered: list[dict] = []
    if len(apollo_filtered) < min_results and departments:
        apollo_unfiltered = await apollo_client.search_people(
            company_name,
            titles=titles,
            seniority=seniority,
            limit=limit,
        )
    if debug_bucket is not None:
        debug_bucket["apollo"] = {
            "filtered_count": len(apollo_filtered),
            "unfiltered_count": len(apollo_unfiltered),
            "filtered_results": [_debug_candidate_summary(item) for item in apollo_filtered[:5]],
            "unfiltered_results": [_debug_candidate_summary(item) for item in apollo_unfiltered[:5]],
        }

    brave_results = []
    merged = _dedupe_candidates(apollo_filtered, apollo_unfiltered)
    linkedin_provider_traces: list[dict[str, Any]] | None = [] if debug_bucket is not None else None
    if len(merged) < min_results:
        brave_results = await search_router_client.search_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            geo_terms=geo_terms,
            limit=max(limit, 5),
            min_results=min_results,
            company_domain=company_domain,
            debug_traces=linkedin_provider_traces,
            search_profile=search_profile,
        )

    public_results = []
    merged = _dedupe_candidates(merged, brave_results)
    public_provider_traces: list[dict[str, Any]] | None = [] if debug_bucket is not None else None
    if len(merged) < min_results or is_ambiguous_company_name(company_name) or bool(public_identity_terms):
        public_results = await search_router_client.search_public_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            public_identity_terms=public_identity_terms,
            geo_terms=geo_terms,
            limit=max(limit, 5),
            min_results=min_results,
            debug_traces=public_provider_traces,
            search_profile=search_profile,
        )

    target_limit = max(limit, 8)
    seed_results = _dedupe_candidates(cached_results, apollo_filtered, apollo_unfiltered)
    mixed_external = _balanced_candidate_mix(
        public_results,
        brave_results,
        limit=max(0, target_limit - len(seed_results)),
    )
    deduped = _dedupe_candidates(seed_results, mixed_external)
    if debug_bucket is not None:
        debug_bucket["linkedin_provider_traces"] = linkedin_provider_traces or []
        debug_bucket["public_provider_traces"] = public_provider_traces or []
        debug_bucket["returned_candidates"] = [_debug_candidate_summary(item) for item in deduped[:10]]
    return deduped[:target_limit]


async def _score_contextual_candidates(
    candidates: list[dict],
    *,
    job: Job,
    context: JobContext,
    min_relevance_score: int,
) -> list[dict]:
    if not candidates:
        return []

    scored = await score_candidate_relevance(
        candidates,
        job_title=job.title,
        company_name=job.company_name,
        team_keywords=context.team_keywords + context.domain_keywords,
        department=context.department,
        min_score=min_relevance_score,
    )
    return scored or candidates


def _heuristic_relevance_score(
    candidate: dict,
    *,
    bucket: str,
    job: Job,
    context: JobContext,
) -> int:
    usefulness = _compute_usefulness_score(
        candidate,
        bucket=bucket,
        context=context,
        company_name=job.company_name,
        public_identity_slugs=None,
    )
    team_rank = _team_keyword_match_rank(candidate, bucket=bucket, context=context)
    location_rank = _location_match_rank(candidate, context=context)
    if usefulness >= 90 or (team_rank == 0 and location_rank == 0):
        return 5
    if usefulness >= 75 or team_rank == 0:
        return 4
    if usefulness >= 55 or location_rank == 0:
        return 3
    if usefulness >= 35:
        return 2
    return 1


def _score_contextual_candidates_fast(
    candidates: list[dict],
    *,
    job: Job,
    context: JobContext,
    min_relevance_score: int,
    bucket: str,
) -> list[dict]:
    if not candidates:
        return []

    enriched: list[dict] = []
    for raw in candidates:
        candidate = dict(raw)
        candidate["relevance_score"] = _heuristic_relevance_score(
            candidate,
            bucket=bucket,
            job=job,
            context=context,
        )
        enriched.append(candidate)

    filtered = [
        candidate
        for candidate in enriched
        if candidate.get("relevance_score", 0) >= min_relevance_score
    ]
    ranked = filtered or enriched
    ranked.sort(
        key=lambda item: (
            -item.get("relevance_score", 0),
            -_compute_usefulness_score(
                item,
                bucket=bucket,
                context=context,
                company_name=job.company_name,
                public_identity_slugs=None,
            ),
            _normalize_identity(item.get("full_name")),
        )
    )
    return ranked


async def _backfill_top_candidates(
    candidates: list[dict],
    *,
    top_n: int,
    company_name: str,
    public_identity_slugs: list[str] | None,
    bucket: str,
    context: JobContext | None = None,
    geo_terms: list[str] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    if not candidates or top_n <= 0:
        return candidates
    head = await _backfill_linkedin_profiles(
        candidates[:top_n],
        company_name=company_name,
        public_identity_slugs=public_identity_slugs,
        bucket=bucket,
        context=context,
        geo_terms=geo_terms,
        search_profile=search_profile,
    )
    return head + candidates[top_n:]


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
    await db.flush()
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
        email_source=data.get("source") if data.get("work_email") else None,
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


def _apply_match_metadata(
    person: Person,
    data: dict,
    person_type: str,
    context: JobContext | None,
    company_name: str | None = None,
    public_identity_slugs: list[str] | None = None,
) -> None:
    match_quality, match_reason = _compute_match_metadata(data, person_type, context)
    employment_status = data.get("_employment_status")
    if not employment_status and company_name:
        employment_status = _classify_employment_status(data, company_name)
    org_level = data.get("_org_level") or _classify_org_level(
        person.title or data.get("title", ""),
        source=data.get("source", ""),
        snippet=data.get("snippet", ""),
    )

    if data.get("_director_fallback"):
        match_quality = "next_best"
        match_reason = "Senior leader fallback at the target company."

    bucket_name = {
        "recruiter": "recruiters",
        "hiring_manager": "hiring_managers",
        "peer": "peers",
    }.get(person_type, "peers")
    usefulness = _compute_usefulness_score(
        data,
        bucket=bucket_name,
        context=context,
        company_name=company_name or "",
        public_identity_slugs=public_identity_slugs,
    )

    setattr(person, "match_quality", match_quality)
    setattr(person, "match_reason", match_reason)
    setattr(person, "company_match_confidence", None)
    setattr(person, "fallback_reason", match_reason if match_quality == "next_best" else None)
    setattr(person, "employment_status", employment_status)
    setattr(person, "org_level", org_level)
    setattr(person, "usefulness_score", usefulness)


def _append_bucket(
    bucketed: dict[str, list[Person]],
    seen: dict[str, set[str]],
    person: Person,
    data: dict,
    explicit_type: str | None = None,
    context: JobContext | None = None,
    company_name: str | None = None,
    public_identity_slugs: list[str] | None = None,
) -> None:
    person_type = explicit_type or _classify_person(
        person.title or data.get("title", ""),
        source=data.get("source", ""),
        snippet=data.get("snippet", ""),
    )
    person.person_type = person_type
    _apply_match_metadata(
        person, data, person_type, context,
        company_name=company_name,
        public_identity_slugs=public_identity_slugs,
    )

    bucket_name = {
        "recruiter": "recruiters",
        "hiring_manager": "hiring_managers",
        "peer": "peers",
    }[person_type]
    profile_data = person.profile_data if isinstance(person.profile_data, dict) else {}
    identity_key = (
        str(person.id)
        if person.id
        else normalize_linkedin_url(person.linkedin_url or "")
        or str(profile_data.get("public_url") or "")
        or _candidate_key(data)
    )
    if identity_key in seen[bucket_name]:
        return
    seen[bucket_name].add(identity_key)
    bucketed[bucket_name].append(person)


def _company_match_confidence(person: Person) -> str | None:
    if person.current_company_verified is True:
        return "verified"
    if getattr(person, "employment_status", None) == "current":
        return "strong_signal"
    if getattr(person, "employment_status", None) == "ambiguous":
        return "weak_signal"
    return None


def _confidence_rank(value: str | None) -> int:
    return {
        "verified": 0,
        "strong_signal": 1,
        "weak_signal": 2,
    }.get(value or "", 3)


def _match_rank(value: str | None) -> int:
    return {
        "direct": 0,
        "adjacent": 1,
        "next_best": 2,
    }.get(value or "", 3)


def _bucket_role_fit_rank(bucket: str, person: Person) -> int:
    title = person.title or ""
    if bucket == "recruiters":
        if _is_recruiter_like(title):
            return 0
        if _is_adjacent_recruiter_like(title):
            return 1
        return 2
    if bucket == "hiring_managers":
        if _is_manager_like(title) or getattr(person, "org_level", None) == "manager":
            return 0
        if _is_senior_ic_fallback(title):
            return 2
        return 1
    if _is_senior_ic_fallback(title):
        return 1
    return 0 if getattr(person, "org_level", None) == "ic" else 1


def _warm_path_rank(person: Person) -> int:
    warm_path_type = getattr(person, "warm_path_type", None)
    is_stale = bool(getattr(person, "warm_path_stale", False))
    refresh_recommended = bool(getattr(person, "warm_path_refresh_recommended", False))

    if warm_path_type == "direct_connection":
        return 1 if is_stale else 0
    if warm_path_type == "same_company_bridge":
        return 2 if (is_stale or refresh_recommended) else 1
    return 2


def _person_location_match_rank(person: Person) -> int:
    raw_profile_data = getattr(person, "profile_data", None)
    profile_data = raw_profile_data if isinstance(raw_profile_data, dict) else {}
    location = (
        getattr(person, "location", None)
        or profile_data.get("location")
        or ""
    )
    if not location:
        return 1
    location_text = str(location).lower()
    if any(term in location_text for term in ("toronto", "greater toronto area", "gta", "mississauga", "ontario")):
        return 0
    return 1


def _peer_person_title_alignment_rank(person: Person) -> int:
    title = (person.title or "").lower()
    if not title:
        return 2
    if any(term in title for term in ("full stack", "fullstack", "software engineer", "software developer", "frontend developer", "frontend engineer", "backend engineer")):
        return 0
    if any(term in title for term in ("machine learning", "applied scientist", "data scientist", "security engineer")):
        return 2
    if any(term in title for term in ("engineer", "developer")):
        return 1
    return 2


def _manager_person_title_specificity_rank(person: Person) -> int:
    return _manager_title_specificity_rank({"title": person.title or ""})


def _recruiter_person_scope_rank(person: Person) -> int:
    profile_data = person.profile_data if isinstance(person.profile_data, dict) else {}
    return _recruiter_scope_rank_from_text(
        person.title or "",
        getattr(person, "headline", "") or "",
        str(profile_data.get("snippet") or ""),
        str(profile_data.get("linkedin_result_title") or ""),
        str(profile_data.get("public_snippet") or ""),
    )


def _bucketed_linkedin_slugs(bucketed: dict[str, list[Person]]) -> list[str]:
    slugs: set[str] = set()
    for people in bucketed.values():
        for person in people:
            normalized = normalize_linkedin_url(person.linkedin_url)
            if normalized:
                slugs.add(normalized.rstrip("/").rsplit("/", 1)[-1])
    return sorted(slugs)


def _dedupe_bucket_assignments(bucketed: dict[str, list[Person]]) -> dict[str, list[Person]]:
    winners: dict[uuid.UUID, tuple[str, tuple[int, int, int, int, int, int, str]]] = {}
    for bucket, people in bucketed.items():
        for person in people:
            if not person.id:
                continue
            usefulness = getattr(person, "usefulness_score", None) or 0
            rank = (
                _match_rank(getattr(person, "match_quality", None)),
                100 - usefulness,
                _bucket_role_fit_rank(bucket, person),
                0 if getattr(person, "company_match_confidence", None) == "verified" else 1,
                _warm_path_rank(person),
                0 if person.linkedin_url else 1,
                _normalize_identity(person.full_name),
            )
            current = winners.get(person.id)
            if current is None or rank < current[1]:
                winners[person.id] = (bucket, rank)

    deduped: dict[str, list[Person]] = {}
    for bucket, people in bucketed.items():
        deduped[bucket] = [
            person
            for person in people
            if not person.id or winners.get(person.id, (None, None))[0] == bucket
        ]
    return deduped


def _finalize_bucketed(
    bucketed: dict[str, list[Person]],
    *,
    target_count_per_bucket: int,
) -> dict[str, list[Person]]:
    finalized: dict[str, list[Person]] = {}
    for bucket, people in bucketed.items():
        ordered: list[Person] = []
        for person in people:
            company_match_confidence = _company_match_confidence(person)
            setattr(person, "company_match_confidence", company_match_confidence)

            if company_match_confidence != "verified":
                setattr(person, "match_quality", "next_best")
                if not getattr(person, "fallback_reason", None):
                    fallback_reason = (
                        "Strong same-company signal, but current employment is not fully verified."
                        if company_match_confidence == "strong_signal"
                        else "Lower-confidence same-company fallback."
                    )
                    setattr(person, "fallback_reason", fallback_reason)
            else:
                setattr(person, "fallback_reason", None)

            ordered.append(person)

        ordered.sort(
            key=lambda person: (
                0
                if getattr(person, "company_match_confidence", None) in {"verified", "strong_signal"}
                else 1,
                _manager_person_title_specificity_rank(person) if bucket == "hiring_managers" else 0,
                _recruiter_person_scope_rank(person) if bucket == "recruiters" else 1,
                _person_location_match_rank(person) if bucket in {"recruiters", "peers"} else 1,
                _peer_person_title_alignment_rank(person) if bucket == "peers" else 1,
                _warm_path_rank(person),
                -(getattr(person, "usefulness_score", None) or 0),
                _match_rank(getattr(person, "match_quality", None)),
                _org_rank(bucket, getattr(person, "org_level", "ic") or "ic"),
                _confidence_rank(getattr(person, "company_match_confidence", None)),
                0 if person.linkedin_url else 1,
                _normalize_identity(person.full_name),
            )
        )
        finalized[bucket] = ordered
    deduped = _dedupe_bucket_assignments(finalized)
    return {
        bucket: people[:target_count_per_bucket]
        for bucket, people in deduped.items()
    }


def _backfill_sparse_hiring_manager_bucket(
    bucketed: dict[str, list[Person]],
    *,
    target_count_per_bucket: int,
) -> None:
    if len(bucketed.get("hiring_managers", [])) >= target_count_per_bucket:
        return

    existing_ids = {person.id for person in bucketed.get("hiring_managers", []) if person.id}
    for person in bucketed.get("peers", []):
        if person.id in existing_ids:
            continue
        confidence = _company_match_confidence(person)
        if confidence not in {"verified", "strong_signal"}:
            continue
        if not (_is_senior_ic_fallback(person.title) or getattr(person, "org_level", None) in {"manager", "director_plus"}):
            continue

        fallback_person = copy.copy(person)
        fallback_person.person_type = "hiring_manager"
        fallback_person.match_quality = "next_best"
        fallback_person.match_reason = "Senior IC fallback at the target company."
        fallback_person.fallback_reason = "Senior IC fallback at the target company."
        fallback_person.org_level = getattr(person, "org_level", None) or "ic"
        bucketed["hiring_managers"].append(fallback_person)
        existing_ids.add(fallback_person.id)
        if len(bucketed["hiring_managers"]) >= target_count_per_bucket:
            return


def _build_roles_context(roles: list[str] | None) -> JobContext | None:
    """Build a lightweight JobContext from user-provided roles for ranking.

    Extracts team keywords from role titles (e.g. "Engineering Manager" → "engineering")
    so that candidate ranking can prefer relevant managers over random directors.
    """
    if not roles:
        return None

    # Extract meaningful keywords from role titles
    STOP_WORDS = {
        "manager", "director", "lead", "head", "senior", "junior", "staff",
        "principal", "vp", "vice", "president", "chief", "officer", "coordinator",
        "specialist", "analyst", "associate", "assistant", "intern", "new", "grad",
        "program", "the", "a", "an", "at", "of", "for", "and", "or",
    }
    team_keywords: list[str] = []
    seen: set[str] = set()
    early_career = False
    for role in roles:
        lower = role.lower()
        if any(kw in lower for kw in ("intern", "new grad", "early career", "university", "campus", "emerging talent")):
            early_career = True
        for word in re.split(r"[\s/,]+", lower):
            word = word.strip()
            if word and word not in STOP_WORDS and len(word) > 2 and word not in seen:
                seen.add(word)
                team_keywords.append(word)

    if not team_keywords:
        return None

    # Guess department from keywords
    department = "engineering"
    if any(kw in team_keywords for kw in ("product", "design", "ux")):
        department = "product_management"
    elif any(kw in team_keywords for kw in ("data", "science", "analytics")):
        department = "data_science"
    elif any(kw in team_keywords for kw in ("marketing", "growth")):
        department = "marketing"

    # Determine appropriate seniority level
    seniority = "mid"
    if early_career:
        has_intern = any("intern" in r.lower() for r in roles)
        seniority = "intern" if has_intern else "junior"

    return JobContext(
        department=department,
        team_keywords=team_keywords,
        domain_keywords=[],
        seniority=seniority,
        early_career=early_career,
        manager_titles=[r for r in roles if _is_manager_like(r)],
        peer_titles=[r for r in roles if not _is_manager_like(r) and not _is_recruiter_like(r)],
        recruiter_titles=[r for r in roles if _is_recruiter_like(r)],
    )


async def search_people_at_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
    roles: list[str] | None = None,
    github_org: str | None = None,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
) -> dict:
    """Find people at a company using company-level search."""
    import time as _time

    from app.models.search_log import SearchLog

    _t0 = _time.monotonic()
    target_count_per_bucket = _clamp_target_count_per_bucket(target_count_per_bucket)
    search_limit = _search_limit_for_target(target_count_per_bucket)
    prepare_limit = _prepare_limit_for_target(target_count_per_bucket)
    minimum_results = _minimum_results_for_target(target_count_per_bucket)

    roles_context = _build_roles_context(roles)

    company = await get_or_create_company(db, user_id, company_name)
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    # Split user-provided roles into the correct buckets instead of dumping
    # all roles into every search.  Recruiter-like roles feed the recruiter
    # search, manager-like roles feed the manager search, and everything else
    # feeds the peer search.  Buckets always fall back to companywide defaults
    # so that we never search for "University Recruiter" in the manager bucket.
    recruiter_titles = _companywide_recruiter_titles(roles_context)
    manager_titles = _companywide_manager_titles(roles_context)
    peer_titles = _companywide_peer_titles(roles_context)
    if roles:
        extra_recruiter = [r for r in roles if _is_recruiter_like(r)]
        extra_manager = [r for r in roles if _is_manager_like(r) and not _is_recruiter_like(r)]
        extra_peer = [r for r in roles if not _is_recruiter_like(r) and not _is_manager_like(r)]
        if extra_recruiter:
            recruiter_titles = list(dict.fromkeys(extra_recruiter + recruiter_titles))
        if extra_manager:
            manager_titles = list(dict.fromkeys(extra_manager + manager_titles))
        if extra_peer:
            peer_titles = list(dict.fromkeys(extra_peer + peer_titles))

    # Run all three bucket searches concurrently for ~3x faster initial discovery
    recruiter_candidates, manager_candidates, peer_candidates = await asyncio.gather(
        _search_candidates(
            company_name,
            titles=recruiter_titles,
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
            db=db,
        ),
        _search_candidates(
            company_name,
            titles=manager_titles,
            seniority=["manager", "director", "vp"],
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
            db=db,
        ),
        _search_candidates(
            company_name,
            titles=peer_titles,
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
            db=db,
        ),
    )
    # For early-career searches, run additional queries with common intern/new-grad
    # phrasing since LinkedIn profiles use varied title formats (e.g. "SWE Intern",
    # "Software Engineer Intern", "Incoming SWE Intern") and a single query batch
    # often returns mostly former interns or posts rather than current profiles.
    if roles_context and roles_context.early_career:
        early_career_titles = [
            "SWE Intern",
            "Software Engineer",
            "Production Engineer",
            "New Grad",
        ]
        extra_peers = await _search_candidates(
            company_name,
            titles=early_career_titles,
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
        )
        peer_candidates = _dedupe_candidates(peer_candidates, extra_peers)
    saved_slug_candidates = await _saved_theorg_slug_candidates(
        db,
        user_id=user_id,
        company=company,
    )
    _merge_company_public_identity_slugs(
        company,
        company_name,
        _candidate_theorg_slug_candidates(
            recruiter_candidates,
            manager_candidates,
            peer_candidates,
            company_name=company_name,
            trusted_slugs=public_identity_terms,
        )
        + saved_slug_candidates,
    )
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    recruiter_candidates, manager_candidates, peer_candidates = await asyncio.gather(
        _recover_candidate_titles(recruiter_candidates, company=company, company_name=company_name),
        _recover_candidate_titles(manager_candidates, company=company, company_name=company_name),
        _recover_candidate_titles(peer_candidates, company=company, company_name=company_name),
    )

    # --- Write-through to global known people cache ---
    try:
        from app.services.known_people_service import write_candidates_to_cache
        all_candidates = recruiter_candidates + manager_candidates + peer_candidates
        await write_candidates_to_cache(
            db,
            all_candidates,
            company_name=company_name,
            company_domain=company.domain if hasattr(company, "domain") else None,
        )
    except Exception:
        logger.debug("Known people cache write-through failed for %s", company_name, exc_info=True)

    recruiter_results = _prepare_candidates(
        recruiter_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="recruiters",
        context=roles_context,
        limit=prepare_limit,
    )
    manager_results = _prepare_candidates(
        manager_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
        context=roles_context,
        limit=prepare_limit,
    )
    peer_results = _prepare_candidates(
        peer_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
        context=roles_context,
        limit=prepare_limit,
    )

    if _should_expand_with_theorg(
        company_name,
        {
            "recruiters": len(recruiter_results),
            "hiring_managers": len(manager_results),
            "peers": len(peer_results),
        },
        context=roles_context,
        target_count_per_bucket=target_count_per_bucket,
    ):
        theorg_candidates = await discover_theorg_candidates(
            company,
            company_name=company_name,
            context=roles_context,
            current_counts={
                "recruiters": len(recruiter_results),
                "hiring_managers": len(manager_results),
                "peers": len(peer_results),
            },
            slug_candidates=_candidate_theorg_slug_candidates(
                recruiter_candidates,
                manager_candidates,
                peer_candidates,
                company_name=company_name,
                trusted_slugs=public_identity_terms,
            )
            + saved_slug_candidates,
        )
        recruiter_results = _prepare_candidates(
            _dedupe_candidates(recruiter_candidates, theorg_candidates.get("recruiters", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=roles_context,
            limit=prepare_limit,
        )
        manager_results = _prepare_candidates(
            _dedupe_candidates(manager_candidates, theorg_candidates.get("hiring_managers", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=roles_context,
            limit=prepare_limit,
        )
        peer_results = _prepare_candidates(
            _dedupe_candidates(peer_candidates, theorg_candidates.get("peers", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=roles_context,
            limit=prepare_limit,
        )

    recruiter_results, manager_results, peer_results = await asyncio.gather(
        _backfill_linkedin_profiles(
            recruiter_results, company_name=company_name,
            public_identity_slugs=public_identity_terms, bucket="recruiters",
        ),
        _backfill_linkedin_profiles(
            manager_results, company_name=company_name,
            public_identity_slugs=public_identity_terms, bucket="hiring_managers",
        ),
        _backfill_linkedin_profiles(
            peer_results, company_name=company_name,
            public_identity_slugs=public_identity_terms, bucket="peers",
        ),
    )

    if any(
        _needs_more_bucket_candidates(results, target_count_per_bucket=target_count_per_bucket)
        for results in (recruiter_results, manager_results, peer_results)
    ):
        if _needs_more_bucket_candidates(recruiter_results, target_count_per_bucket=target_count_per_bucket):
            recruiter_candidates = _dedupe_candidates(
                recruiter_candidates,
                await _search_candidates(
                    company_name,
                    titles=_companywide_recruiter_titles(roles_context),
                    public_identity_terms=public_identity_terms,
                    limit=search_limit,
                    min_results=minimum_results,
                ),
            )
            recruiter_candidates = await _recover_candidate_titles(
                recruiter_candidates,
                company=company,
                company_name=company_name,
            )
            recruiter_results = _prepare_candidates(
                recruiter_candidates,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="recruiters",
                context=roles_context,
                limit=prepare_limit,
            )
            recruiter_results = await _backfill_linkedin_profiles(
                recruiter_results,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="recruiters",
            )

        if _needs_more_bucket_candidates(manager_results, target_count_per_bucket=target_count_per_bucket):
            manager_candidates = _dedupe_candidates(
                manager_candidates,
                await _search_candidates(
                    company_name,
                    titles=_companywide_manager_titles(roles_context),
                    seniority=["manager", "director", "vp"],
                    public_identity_terms=public_identity_terms,
                    limit=search_limit,
                    min_results=minimum_results,
                ),
            )
            manager_candidates = await _recover_candidate_titles(
                manager_candidates,
                company=company,
                company_name=company_name,
            )
            manager_results = _prepare_candidates(
                manager_candidates,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
                context=roles_context,
                limit=prepare_limit,
            )
            manager_results = await _backfill_linkedin_profiles(
                manager_results,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
            )

        if _needs_more_bucket_candidates(peer_results, target_count_per_bucket=target_count_per_bucket):
            peer_candidates = _dedupe_candidates(
                peer_candidates,
                await _search_candidates(
                    company_name,
                    titles=_companywide_peer_titles(roles_context, fallback_titles=peer_titles),
                    public_identity_terms=public_identity_terms,
                    limit=search_limit,
                    min_results=minimum_results,
                ),
            )
            peer_candidates = await _recover_candidate_titles(
                peer_candidates,
                company=company,
                company_name=company_name,
            )
            peer_results = _prepare_candidates(
                peer_candidates,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
                context=roles_context,
                limit=prepare_limit,
            )
            peer_results = await _backfill_linkedin_profiles(
                peer_results,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
            )

    bucket_candidate_groups = _dedupe_candidate_bucket_groups(
        {
            "recruiters": recruiter_results,
            "hiring_managers": manager_results,
            "peers": peer_results,
        },
        context=roles_context,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
    )
    recruiter_results = bucket_candidate_groups["recruiters"]
    manager_results = bucket_candidate_groups["hiring_managers"]
    peer_results = bucket_candidate_groups["peers"]

    github_members: list[dict] = []
    if github_org:
        github_members = await github_client.search_org_members(
            github_org,
            limit=max(5, target_count_per_bucket),
        )
        for member in github_members:
            repos = await github_client.get_user_repos(member["login"], limit=3)
            languages = list({repo["language"] for repo in repos if repo.get("language")})
            member["github_data"] = {"repos": repos, "languages": languages}
            member["github_url"] = member.get("github_url", "")

    bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
    seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}

    for data in recruiter_results:
        person = await _store_person(db, user_id, company, data, "recruiter")
        _append_bucket(bucketed, seen, person, data, explicit_type="recruiter", context=roles_context, company_name=company_name, public_identity_slugs=public_identity_terms)

    for data in manager_results:
        person = await _store_person(
            db,
            user_id,
            company,
            data,
            _classify_person(data.get("title", "")),
        )
        _append_bucket(bucketed, seen, person, data, context=roles_context, company_name=company_name, public_identity_slugs=public_identity_terms)

    for data in peer_results:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", context=roles_context, company_name=company_name, public_identity_slugs=public_identity_terms)

    for data in github_members:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", context=roles_context, company_name=company_name)

    await verify_people_current_company(
        bucketed,
        company_name=company_name,
        company_domain=company.domain if company.domain_trusted else None,
        company_public_identity_slugs=public_identity_terms,
    )
    _backfill_sparse_hiring_manager_bucket(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
    )
    your_connections = await linkedin_graph_service.get_connections_for_company(
        db,
        user_id,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
    )
    direct_connections = await linkedin_graph_service.get_connections_by_linkedin_slugs(
        db,
        user_id,
        _bucketed_linkedin_slugs(bucketed),
    )
    linkedin_graph_service.apply_warm_path_annotations(
        bucketed,
        company_name=company_name,
        your_connections=your_connections,
        direct_connections=direct_connections,
    )
    finalized = _finalize_bucketed(bucketed, target_count_per_bucket=target_count_per_bucket)

    # Record search in audit log
    elapsed = _time.monotonic() - _t0
    search_log = SearchLog(
        user_id=user_id,
        company_id=company.id,
        company_name=company_name,
        search_type="company",
        recruiter_count=len(finalized["recruiters"]),
        manager_count=len(finalized["hiring_managers"]),
        peer_count=len(finalized["peers"]),
        duration_seconds=round(elapsed, 2),
    )
    db.add(search_log)
    await db.commit()

    return {
        "company": company,
        "your_connections": [
            linkedin_graph_service.serialize_connection(connection)
            for connection in your_connections
        ],
        **finalized,
    }


async def search_people_for_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    search_depth: str = "deep",
    min_relevance_score: int = 1,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
    include_debug: bool = False,
) -> dict:
    """Find people at a company using extracted job context."""
    total_started_at = time.monotonic()
    target_count_per_bucket = _clamp_target_count_per_bucket(target_count_per_bucket)
    search_limit = _search_limit_for_target(target_count_per_bucket)
    prepare_limit = _prepare_limit_for_target(target_count_per_bucket)
    minimum_results = _minimum_results_for_target(target_count_per_bucket)
    interactive_enrichment_limit = _interactive_enrichment_limit_for_target(target_count_per_bucket)
    interactive_backfill_limit = min(target_count_per_bucket, 3)
    interactive_search_profile = "interactive_fast" if search_depth == "fast" else "interactive"
    deep_recovery_enabled = search_depth != "fast"

    stage_started_at = time.monotonic()
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    context = extract_job_context(job.title, job.description)

    # Populate job locations for location-aware ranking
    if job.location:
        context.job_locations = normalize_job_locations(job.location)
    if context.job_locations and not job.remote:
        context.job_geo_terms = build_job_geo_terms(context.job_locations)

    recruiter_min_results = minimum_results
    manager_min_results = minimum_results
    peer_min_results = minimum_results
    recruiter_geo_terms = _bucket_geo_terms(context, bucket="recruiters") or None
    manager_geo_terms = _bucket_geo_terms(context, bucket="hiring_managers") or None
    peer_geo_terms = _bucket_geo_terms(context, bucket="peers") or None

    debug: dict[str, Any] | None = None
    if include_debug:
        debug = {
            "job": {
                "id": str(job.id),
                "title": job.title,
                "company_name": job.company_name,
                "location": job.location,
                "remote": job.remote,
                "search_depth": search_depth,
            },
            "geo": {
                "job_locations": context.job_locations,
                "job_geo_terms": context.job_geo_terms,
                "bucket_geo_terms": {
                    "recruiters": recruiter_geo_terms or [],
                    "hiring_managers": manager_geo_terms or [],
                    "peers": peer_geo_terms or [],
                },
            },
            "searches": {},
            "funnels": {},
            "final": {},
        }
    _record_timing(
        debug,
        stage="job_load_and_context",
        started_at=stage_started_at,
        company_name=job.company_name,
        interactive_enrichment_limit=interactive_enrichment_limit,
        interactive_backfill_limit=interactive_backfill_limit,
    )

    company_started_at = time.monotonic()
    company = await get_or_create_company(
        db,
        user_id,
        job.company_name,
        ats_slug=job.ats_slug,
        careers_url=job.url,
    )
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    # For ambiguous companies, resolve a domain for search disambiguation
    search_domain: str | None = None
    if is_ambiguous_company_name(job.company_name):
        search_domain = company.domain if company.domain_trusted else None
        if not search_domain:
            hints = company.identity_hints if isinstance(company.identity_hints, dict) else {}
            normalized = normalize_company_name(job.company_name)
            dr = (hints.get("domain_root") or "").strip().lower()
            if dr and dr != normalized:
                search_domain = dr
            if not search_domain:
                li_slug = (hints.get("linkedin_company_slug") or "").strip().lower()
                if li_slug and li_slug != normalized:
                    common_tlds = ("ai", "io", "co", "app", "dev", "tech", "xyz", "com", "org", "net")
                    derived_domain = None
                    if li_slug.startswith(normalized):
                        suffix = li_slug[len(normalized):]
                        if suffix in common_tlds:
                            derived_domain = f"{normalized}.{suffix}"
                    search_domain = derived_domain or li_slug
            if not search_domain:
                ch = (hints.get("careers_host") or "").strip().lower()
                if ch and not any(root in ch for root in ("lever", "greenhouse", "ashby", "workable", "workday")):
                    search_domain = ch
    _record_timing(
        debug,
        stage="company_resolution",
        started_at=company_started_at,
        company_id=str(company.id) if company.id else None,
        search_domain=search_domain,
    )
    recruiter_titles = _prioritize_titles_for_search(
        context.recruiter_titles,
        bucket="recruiters",
        context=context,
    )
    manager_titles = _initial_manager_titles(context)
    peer_titles = _prioritize_titles_for_search(
        context.peer_titles,
        bucket="peers",
        context=context,
    )

    # Build search keywords: product/team names first (most specific), then
    # generic team + domain keywords.  Product names like "Data Cloud" scope
    # searches to the right part of a large org.
    product_names = getattr(context, "product_team_names", []) or []
    search_keywords = _sanitize_search_keywords(
        product_names + context.team_keywords + context.domain_keywords,
        company_name=job.company_name,
    )

    recruiter_search_started_at = time.monotonic()
    recruiter_candidates = await _search_candidates(
        job.company_name,
        titles=recruiter_titles,
        departments=context.apollo_departments,
        team_keywords=search_keywords,
        geo_terms=recruiter_geo_terms,
        public_identity_terms=public_identity_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=recruiter_min_results,
        debug_bucket=debug["searches"].setdefault("recruiters_initial", {}) if debug is not None else None,
        search_profile=interactive_search_profile,
    )
    _record_timing(
        debug,
        stage="recruiters_initial_search",
        started_at=recruiter_search_started_at,
        recruiter_candidates=len(recruiter_candidates),
    )
    manager_search_started_at = time.monotonic()
    manager_candidates = await _search_candidates(
        job.company_name,
        titles=manager_titles,
        departments=context.apollo_departments,
        seniority=_manager_seniority_filters(context),
        team_keywords=search_keywords,
        geo_terms=manager_geo_terms,
        public_identity_terms=public_identity_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=manager_min_results,
        debug_bucket=debug["searches"].setdefault("hiring_managers_initial", {}) if debug is not None else None,
        search_profile=interactive_search_profile,
    )
    _record_timing(
        debug,
        stage="hiring_managers_initial_search",
        started_at=manager_search_started_at,
        manager_candidates=len(manager_candidates),
    )
    peer_search_started_at = time.monotonic()
    peer_candidates = await _search_candidates(
        job.company_name,
        titles=peer_titles,
        departments=context.apollo_departments,
        seniority=_peer_seniority_filters(context),
        team_keywords=search_keywords,
        geo_terms=peer_geo_terms,
        public_identity_terms=public_identity_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=peer_min_results,
        debug_bucket=debug["searches"].setdefault("peers_initial", {}) if debug is not None else None,
        search_profile=interactive_search_profile,
    )
    _record_timing(
        debug,
        stage="initial_bucket_searches",
        started_at=peer_search_started_at,
        recruiter_candidates=len(recruiter_candidates),
        manager_candidates=len(manager_candidates),
        peer_candidates=len(peer_candidates),
    )
    # For ambiguous companies, run a broad employee discovery without title constraints
    # since title-specific queries get polluted by people sharing the company name
    if search_domain and is_ambiguous_company_name(job.company_name):
        ambiguous_search_started_at = time.monotonic()
        broad_employee_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        broad_employees = await search_router_client.search_people(
            job.company_name,
            titles=None,
            team_keywords=None,
            geo_terms=manager_geo_terms or context.job_geo_terms or None,
            limit=max(search_limit, 15),
            min_results=5,
            company_domain=search_domain,
            debug_traces=broad_employee_traces,
            search_profile=interactive_search_profile,
        )
        if debug is not None:
            debug["searches"]["ambiguous_company_broad_employees"] = {
                "provider_traces": broad_employee_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in broad_employees[:10]],
            }
        recruiter_candidates = _dedupe_candidates(recruiter_candidates, broad_employees)
        manager_candidates = _dedupe_candidates(manager_candidates, broad_employees)
        peer_candidates = _dedupe_candidates(peer_candidates, broad_employees)
        _record_timing(
            debug,
            stage="ambiguous_company_broad_employees",
            started_at=ambiguous_search_started_at,
            broad_employees=len(broad_employees),
        )

    hiring_team_traces: list[dict[str, Any]] | None = [] if debug is not None else None
    hiring_team_started_at = time.monotonic()
    hiring_team_candidates = await search_router_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        geo_terms=manager_geo_terms,
        limit=max(5, min(target_count_per_bucket + 2, 8)),
        min_results=1,
        debug_traces=hiring_team_traces,
        search_profile=interactive_search_profile,
    )
    if debug is not None:
        debug["searches"]["hiring_team_initial"] = {
            "provider_traces": hiring_team_traces or [],
            "returned_candidates": [_debug_candidate_summary(item) for item in hiring_team_candidates[:10]],
        }
    _record_timing(
        debug,
        stage="initial_hiring_team_search",
        started_at=hiring_team_started_at,
        hiring_team_candidates=len(hiring_team_candidates),
    )

    # Supplementary "actively hiring" search — looks for people who posted
    # about hiring for similar roles.  We search with "hiring" as a team
    # keyword alongside the job title keywords so the results surface
    # managers/recruiters who are actively posting about open roles.
    try:
        actively_hiring_started_at = time.monotonic()
        hiring_signal_keywords = ["hiring", "open role"]
        if context.early_career:
            hiring_signal_keywords.extend(["new grad", "hiring new grads"])
        actively_hiring_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        actively_hiring_candidates = await search_router_client.search_hiring_team(
            job.company_name,
            job.title,
            team_keywords=hiring_signal_keywords,
            geo_terms=recruiter_geo_terms or manager_geo_terms,
            limit=3,
            min_results=0,
            debug_traces=actively_hiring_traces,
            search_profile=interactive_search_profile,
        )
        for candidate in actively_hiring_candidates:
            candidate["_actively_hiring"] = True
            candidate["profile_data"] = {
                **(candidate.get("profile_data") or {}),
                "actively_hiring": True,
            }
        hiring_team_candidates = _dedupe_candidates(hiring_team_candidates, actively_hiring_candidates)
        if debug is not None:
            debug["searches"]["actively_hiring_hiring_team"] = {
                "provider_traces": actively_hiring_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in actively_hiring_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="actively_hiring_hiring_team",
            started_at=actively_hiring_started_at,
            candidates=len(actively_hiring_candidates),
        )
    except Exception:
        logger.debug("Actively-hiring supplementary search failed for %s", job.company_name, exc_info=True)

    # Second supplementary search: target linkedin.com/in profiles of engineers
    # and managers who mention hiring in their profiles or posts.  This finds
    # people like Spencer Chan (Quora) or Abhishek Sehgal (Uber) who post
    # "I'm hiring" or "join my team" — especially valuable at smaller companies
    # where engineers recruit directly.
    try:
        hiring_people_started_at = time.monotonic()
        hiring_people_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        hiring_people_candidates = await search_router_client.search_people(
            job.company_name,
            titles=["hiring", "join my team", "we're hiring"],
            team_keywords=context.team_keywords[:2],
            geo_terms=recruiter_geo_terms or manager_geo_terms,
            limit=3,
            min_results=0,
            debug_traces=hiring_people_traces,
            search_profile=interactive_search_profile,
        )
        for candidate in hiring_people_candidates:
            candidate["_actively_hiring"] = True
            candidate["profile_data"] = {
                **(candidate.get("profile_data") or {}),
                "actively_hiring": True,
            }
        hiring_team_candidates = _dedupe_candidates(hiring_team_candidates, hiring_people_candidates)
        if debug is not None:
            debug["searches"]["actively_hiring_people"] = {
                "provider_traces": hiring_people_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in hiring_people_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="actively_hiring_people_search",
            started_at=hiring_people_started_at,
            candidates=len(hiring_people_candidates),
        )
    except Exception:
        logger.debug("Hiring-people supplementary search failed for %s", job.company_name, exc_info=True)

    recruiter_candidates = _dedupe_candidates(
        recruiter_candidates,
        [candidate for candidate in hiring_team_candidates if _classify_person(candidate.get("title", ""), snippet=candidate.get("snippet", ""), source=candidate.get("source", "")) == "recruiter"],
    )
    manager_candidates = _dedupe_candidates(
        manager_candidates,
        [candidate for candidate in hiring_team_candidates if _classify_person(candidate.get("title", ""), snippet=candidate.get("snippet", ""), source=candidate.get("source", "")) == "hiring_manager"],
    )
    peer_candidates = _dedupe_candidates(
        peer_candidates,
        [candidate for candidate in hiring_team_candidates if _classify_person(candidate.get("title", ""), snippet=candidate.get("snippet", ""), source=candidate.get("source", "")) == "peer"],
    )
    peer_retry_started_at = time.monotonic()
    peer_candidates = await _expand_peer_candidates(
        job.company_name,
        peer_candidates,
        context=context,
        public_identity_terms=public_identity_terms,
        geo_terms=peer_geo_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=max(peer_min_results, target_count_per_bucket),
        debug_bucket=debug["searches"].setdefault("peers_retry", {}) if debug is not None else None,
        search_profile=interactive_search_profile,
    )
    _record_timing(
        debug,
        stage="peer_retry_search",
        started_at=peer_retry_started_at,
        peer_candidates=len(peer_candidates),
    )
    saved_slug_candidates = await _saved_theorg_slug_candidates(
        db,
        user_id=user_id,
        company=company,
    )
    _merge_company_public_identity_slugs(
        company,
        job.company_name,
        _candidate_theorg_slug_candidates(
            recruiter_candidates,
            manager_candidates,
            peer_candidates,
            hiring_team_candidates,
            company_name=job.company_name,
            trusted_slugs=public_identity_terms,
        )
        + saved_slug_candidates,
    )
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    recovery_started_at = time.monotonic()
    recruiter_candidates = await _recover_candidate_titles(
        recruiter_candidates,
        company=company,
        company_name=job.company_name,
    )
    manager_candidates = await _recover_candidate_titles(
        manager_candidates,
        company=company,
        company_name=job.company_name,
    )
    peer_candidates = await _recover_candidate_titles(
        peer_candidates,
        company=company,
        company_name=job.company_name,
    )
    manager_candidates = _dedupe_candidates(
        manager_candidates,
        [candidate for candidate in peer_candidates if _is_senior_ic_fallback(candidate.get("title"))],
    )
    _record_timing(
        debug,
        stage="candidate_title_recovery",
        started_at=recovery_started_at,
        recruiter_candidates=len(recruiter_candidates),
        manager_candidates=len(manager_candidates),
        peer_candidates=len(peer_candidates),
    )

    scoring_started_at = time.monotonic()
    manager_candidates = _score_contextual_candidates_fast(
        manager_candidates,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
        bucket="hiring_managers",
    )
    peer_candidates = _score_contextual_candidates_fast(
        peer_candidates,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
        bucket="peers",
    )
    _record_timing(
        debug,
        stage="contextual_scoring",
        started_at=scoring_started_at,
        manager_candidates=len(manager_candidates),
        peer_candidates=len(peer_candidates),
    )
    prepare_started_at = time.monotonic()
    recruiter_results = _prepare_candidates(
        recruiter_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="recruiters",
        context=context,
        limit=prepare_limit,
        debug_funnel=debug["funnels"].setdefault("recruiters_initial", {}) if debug is not None else None,
    )
    manager_results = _prepare_candidates(
        manager_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
        context=context,
        limit=prepare_limit,
        debug_funnel=debug["funnels"].setdefault("hiring_managers_initial", {}) if debug is not None else None,
    )
    peer_results = _prepare_candidates(
        peer_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
        context=context,
        limit=prepare_limit,
        debug_funnel=debug["funnels"].setdefault("peers_initial", {}) if debug is not None else None,
    )
    recruiter_results = _limit_interactive_bucket(
        recruiter_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    manager_results = _limit_interactive_bucket(
        manager_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    peer_results = _limit_interactive_bucket(
        peer_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    _record_timing(
        debug,
        stage="initial_prepare",
        started_at=prepare_started_at,
        recruiter_results=len(recruiter_results),
        manager_results=len(manager_results),
        peer_results=len(peer_results),
    )
    recruiter_targeted_recovery_needed = _should_run_recruiter_targeted_recovery(
        recruiter_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    )
    manager_geo_recovery_needed = _should_run_manager_geo_recovery(
        manager_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    )
    peer_targeted_recovery_needed = _should_run_peer_targeted_recovery(
        peer_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    )

    if deep_recovery_enabled and recruiter_targeted_recovery_needed:
        recruiter_targeted_started_at = time.monotonic()
        recruiter_targeted_trace: dict[str, Any] | None = {"provider": "tavily_direct", "queries": []} if debug is not None else None
        targeted_recruiter_candidates = await tavily_search_client.search_public_people(
            job.company_name,
            titles=_recruiter_targeted_recovery_titles(context),
            team_keywords=_recruiter_targeted_recovery_keywords(context),
            public_identity_terms=public_identity_terms,
            geo_terms=recruiter_geo_terms,
            limit=search_limit,
            debug_trace=recruiter_targeted_trace,
        )
        recruiter_candidates = _dedupe_candidates(recruiter_candidates, targeted_recruiter_candidates)
        recruiter_candidates = await _recover_candidate_titles(
            recruiter_candidates,
            company=company,
            company_name=job.company_name,
        )
        recruiter_results = _prepare_candidates(
            recruiter_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("recruiters_targeted_public", {}) if debug is not None else None,
        )
        recruiter_results = _limit_interactive_bucket(
            recruiter_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            recruiter_targeted_trace = recruiter_targeted_trace or {"provider": "tavily_direct", "queries": []}
            recruiter_targeted_trace["result_count"] = len(targeted_recruiter_candidates)
            recruiter_targeted_trace["sample_results"] = [
                _debug_candidate_summary(item) for item in targeted_recruiter_candidates[:5]
            ]
            debug["searches"]["recruiters_targeted_public"] = {
                "provider_traces": [recruiter_targeted_trace],
                "returned_candidates": [_debug_candidate_summary(item) for item in targeted_recruiter_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="recruiters_targeted_public",
            started_at=recruiter_targeted_started_at,
            candidates=len(targeted_recruiter_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="recruiters_targeted_public_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_recruiter_bucket_sufficient",
        )

    recruiter_recovery_needed = _should_run_recruiter_targeted_recovery(
        recruiter_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    ) or not _has_recruiter_lead_candidate(recruiter_results)

    if deep_recovery_enabled and recruiter_recovery_needed:
        recruiter_recovery_started_at = time.monotonic()
        recruiter_profile_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        recruiter_post_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        recruiter_profile_candidates = await search_router_client.search_recruiter_recovery_profiles(
            job.company_name,
            team_keywords=_recruiter_targeted_recovery_keywords(context),
            geo_terms=recruiter_geo_terms,
            limit=search_limit,
            min_results=min(target_count_per_bucket, 2),
            debug_traces=recruiter_profile_traces,
            search_profile=interactive_search_profile,
        )
        recruiter_post_candidates = await search_router_client.search_recruiter_recovery_posts(
            job.company_name,
            geo_terms=recruiter_geo_terms,
            limit=search_limit,
            min_results=1,
            debug_traces=recruiter_post_traces,
            search_profile=interactive_search_profile,
        )
        recruiter_candidates = _dedupe_candidates(
            recruiter_candidates,
            recruiter_profile_candidates,
            recruiter_post_candidates,
        )
        recruiter_candidates = await _recover_candidate_titles(
            recruiter_candidates,
            company=company,
            company_name=job.company_name,
        )
        recruiter_results = _prepare_candidates(
            recruiter_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("recruiters_recovery", {}) if debug is not None else None,
        )
        recruiter_results = _limit_interactive_bucket(
            recruiter_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            debug["searches"]["recruiters_recovery_profiles"] = {
                "provider_traces": recruiter_profile_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in recruiter_profile_candidates[:10]],
            }
            debug["searches"]["recruiters_recovery_posts"] = {
                "provider_traces": recruiter_post_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in recruiter_post_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="recruiters_recovery",
            started_at=recruiter_recovery_started_at,
            profile_candidates=len(recruiter_profile_candidates),
            post_candidates=len(recruiter_post_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="recruiters_recovery_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_recruiter_recovery_not_needed",
        )

    if deep_recovery_enabled and manager_geo_recovery_needed:
        manager_geo_public_started_at = time.monotonic()
        tavily_manager_trace: dict[str, Any] | None = {"provider": "tavily_direct", "queries": []} if debug is not None else None
        geo_manager_public_candidates = await tavily_search_client.search_public_people(
            job.company_name,
            titles=_manager_geo_recovery_titles(context),
            team_keywords=_manager_geo_recovery_keywords(context),
            public_identity_terms=public_identity_terms,
            geo_terms=manager_geo_terms,
            limit=search_limit,
            debug_trace=tavily_manager_trace,
        )
        manager_candidates = _dedupe_candidates(manager_candidates, geo_manager_public_candidates)
        manager_candidates = _score_contextual_candidates_fast(
            manager_candidates,
            job=job,
            context=context,
            min_relevance_score=min_relevance_score,
            bucket="hiring_managers",
        )
        manager_results = _prepare_candidates(
            manager_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("hiring_managers_geo_public", {}) if debug is not None else None,
        )
        manager_results = _limit_interactive_bucket(
            manager_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            tavily_manager_trace = tavily_manager_trace or {"provider": "tavily_direct", "queries": []}
            tavily_manager_trace["result_count"] = len(geo_manager_public_candidates)
            tavily_manager_trace["sample_results"] = [
                _debug_candidate_summary(item) for item in geo_manager_public_candidates[:5]
            ]
            debug["searches"]["hiring_managers_geo_public"] = {
                "provider_traces": [tavily_manager_trace],
                "returned_candidates": [_debug_candidate_summary(item) for item in geo_manager_public_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="hiring_managers_geo_public",
            started_at=manager_geo_public_started_at,
            candidates=len(geo_manager_public_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="hiring_managers_geo_public_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_manager_bucket_sufficient",
        )

    if deep_recovery_enabled and peer_targeted_recovery_needed:
        peer_targeted_started_at = time.monotonic()
        peer_targeted_trace: dict[str, Any] | None = {"provider": "tavily_direct", "queries": []} if debug is not None else None
        targeted_peer_candidates = await tavily_search_client.search_public_people(
            job.company_name,
            titles=_peer_targeted_recovery_titles(context),
            team_keywords=_peer_targeted_recovery_keywords(context),
            public_identity_terms=public_identity_terms,
            geo_terms=peer_geo_terms,
            limit=search_limit,
            debug_trace=peer_targeted_trace,
        )
        peer_candidates = _dedupe_candidates(peer_candidates, targeted_peer_candidates)
        peer_candidates = await _recover_candidate_titles(
            peer_candidates,
            company=company,
            company_name=job.company_name,
        )
        peer_candidates = _score_contextual_candidates_fast(
            peer_candidates,
            job=job,
            context=context,
            min_relevance_score=min_relevance_score,
            bucket="peers",
        )
        peer_results = _prepare_candidates(
            peer_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("peers_targeted_public", {}) if debug is not None else None,
        )
        peer_results = _limit_interactive_bucket(
            peer_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            peer_targeted_trace = peer_targeted_trace or {"provider": "tavily_direct", "queries": []}
            peer_targeted_trace["result_count"] = len(targeted_peer_candidates)
            peer_targeted_trace["sample_results"] = [
                _debug_candidate_summary(item) for item in targeted_peer_candidates[:5]
            ]
            debug["searches"]["peers_targeted_public"] = {
                "provider_traces": [peer_targeted_trace],
                "returned_candidates": [_debug_candidate_summary(item) for item in targeted_peer_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="peers_targeted_public",
            started_at=peer_targeted_started_at,
            candidates=len(targeted_peer_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="peers_targeted_public_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_peer_bucket_sufficient",
        )

    if _should_expand_with_theorg(
        job.company_name,
        {
            "recruiters": len(recruiter_results),
            "hiring_managers": len(manager_results),
            "peers": len(peer_results),
        },
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    ):
        theorg_started_at = time.monotonic()
        theorg_candidates = await discover_theorg_candidates(
            company,
            company_name=job.company_name,
            context=context,
            current_counts={
                "recruiters": len(recruiter_results),
                "hiring_managers": len(manager_results),
                "peers": len(peer_results),
            },
            slug_candidates=_candidate_theorg_slug_candidates(
                recruiter_candidates,
                manager_candidates,
                peer_candidates,
                hiring_team_candidates,
                company_name=job.company_name,
                trusted_slugs=public_identity_terms,
            )
            + saved_slug_candidates,
        )
        recruiter_results = _prepare_candidates(
            _dedupe_candidates(recruiter_candidates, theorg_candidates.get("recruiters", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("recruiters_with_theorg", {}) if debug is not None else None,
        )
        manager_results = _prepare_candidates(
            _dedupe_candidates(manager_candidates, theorg_candidates.get("hiring_managers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("hiring_managers_with_theorg", {}) if debug is not None else None,
        )
        peer_results = _prepare_candidates(
            _dedupe_candidates(peer_candidates, theorg_candidates.get("peers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("peers_with_theorg", {}) if debug is not None else None,
        )
        recruiter_results = _limit_interactive_bucket(
            recruiter_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        manager_results = _limit_interactive_bucket(
            manager_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        peer_results = _limit_interactive_bucket(
            peer_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        _record_timing(
            debug,
            stage="theorg_expansion",
            started_at=theorg_started_at,
            recruiter_candidates=len(theorg_candidates.get("recruiters", [])),
            manager_candidates=len(theorg_candidates.get("hiring_managers", [])),
            peer_candidates=len(theorg_candidates.get("peers", [])),
        )

    backfill_started_at = time.monotonic()
    recruiter_results = _mark_linkedin_backfill_deferred(recruiter_results)
    manager_results = _mark_linkedin_backfill_deferred(manager_results)
    peer_results = _mark_linkedin_backfill_deferred(peer_results)
    _record_timing(
        debug,
        stage="linkedin_backfill_deferred",
        started_at=backfill_started_at,
        recruiter_results=len(recruiter_results),
        manager_results=len(manager_results),
        peer_results=len(peer_results),
        deferred=True,
        interactive_backfill_limit=interactive_backfill_limit,
    )

    if deep_recovery_enabled and any(
        _needs_more_bucket_size_only(results, target_count_per_bucket=target_count_per_bucket)
        for results in (recruiter_results, manager_results, peer_results)
    ):
        fallback_started_at = time.monotonic()
        if _needs_more_bucket_size_only(recruiter_results, target_count_per_bucket=target_count_per_bucket):
            recruiter_candidates = _dedupe_candidates(
                recruiter_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_recruiter_titles(context),
                    departments=context.apollo_departments,
                    team_keywords=None,
                    geo_terms=recruiter_geo_terms,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=recruiter_min_results,
                    debug_bucket=debug["searches"].setdefault("recruiters_companywide", {}) if debug is not None else None,
                    search_profile=interactive_search_profile,
                ),
            )
            recruiter_candidates = await _recover_candidate_titles(
                recruiter_candidates,
                company=company,
                company_name=job.company_name,
            )
            recruiter_results = _prepare_candidates(
                recruiter_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="recruiters",
                context=context,
                limit=prepare_limit,
                debug_funnel=debug["funnels"].setdefault("recruiters_companywide", {}) if debug is not None else None,
            )
            recruiter_results = _limit_interactive_bucket(
                recruiter_results,
                target_count_per_bucket=target_count_per_bucket,
            )
            recruiter_results = _mark_linkedin_backfill_deferred(recruiter_results)
        if _needs_more_bucket_size_only(manager_results, target_count_per_bucket=target_count_per_bucket):
            manager_candidates = _dedupe_candidates(
                manager_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_manager_titles(context),
                    departments=context.apollo_departments,
                    seniority=_manager_seniority_filters(context),
                    team_keywords=None,
                    geo_terms=manager_geo_terms,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=manager_min_results,
                    debug_bucket=debug["searches"].setdefault("hiring_managers_companywide", {}) if debug is not None else None,
                    search_profile=interactive_search_profile,
                ),
            )
            manager_candidates = await _recover_candidate_titles(
                manager_candidates,
                company=company,
                company_name=job.company_name,
            )
            manager_candidates = _score_contextual_candidates_fast(
                manager_candidates,
                job=job,
                context=context,
                min_relevance_score=min_relevance_score,
                bucket="hiring_managers",
            )
            manager_results = _prepare_candidates(
                manager_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
                context=context,
                limit=prepare_limit,
                debug_funnel=debug["funnels"].setdefault("hiring_managers_companywide", {}) if debug is not None else None,
            )
            manager_results = _limit_interactive_bucket(
                manager_results,
                target_count_per_bucket=target_count_per_bucket,
            )
            manager_results = _mark_linkedin_backfill_deferred(manager_results)
        if _needs_more_bucket_size_only(peer_results, target_count_per_bucket=target_count_per_bucket):
            peer_candidates = _dedupe_candidates(
                peer_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_peer_titles(context),
                    departments=context.apollo_departments,
                    team_keywords=None,
                    geo_terms=peer_geo_terms,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=peer_min_results,
                    debug_bucket=debug["searches"].setdefault("peers_companywide", {}) if debug is not None else None,
                    search_profile=interactive_search_profile,
                ),
            )
            peer_candidates = await _recover_candidate_titles(
                peer_candidates,
                company=company,
                company_name=job.company_name,
            )
            peer_candidates = _score_contextual_candidates_fast(
                peer_candidates,
                job=job,
                context=context,
                min_relevance_score=min_relevance_score,
                bucket="peers",
            )
            peer_results = _prepare_candidates(
                peer_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
                context=context,
                limit=prepare_limit,
                debug_funnel=debug["funnels"].setdefault("peers_companywide", {}) if debug is not None else None,
            )
            peer_results = _limit_interactive_bucket(
                peer_results,
                target_count_per_bucket=target_count_per_bucket,
            )
            peer_results = _mark_linkedin_backfill_deferred(peer_results)
        _record_timing(
            debug,
            stage="companywide_fallbacks",
            started_at=fallback_started_at,
            recruiter_results=len(recruiter_results),
            manager_results=len(manager_results),
            peer_results=len(peer_results),
        )

    final_hiring_team_traces: list[dict[str, Any]] | None = [] if debug is not None else None
    final_hiring_team_started_at = time.monotonic()
    hiring_team_results = await search_router_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        geo_terms=manager_geo_terms,
        limit=max(3, min(target_count_per_bucket + 1, 6)),
        min_results=1,
        debug_traces=final_hiring_team_traces,
        search_profile=interactive_search_profile,
    )
    if debug is not None:
        debug["searches"]["hiring_team_final"] = {
            "provider_traces": final_hiring_team_traces or [],
            "returned_candidates": [_debug_candidate_summary(item) for item in hiring_team_results[:10]],
        }
    _record_timing(
        debug,
        stage="final_hiring_team_search",
        started_at=final_hiring_team_started_at,
        candidates=len(hiring_team_results),
    )

    validated_hiring_team_results: list[dict] = []
    for raw in hiring_team_results:
        if not _candidate_matches_company(raw, job.company_name, public_identity_terms):
            continue
        employment_status = _classify_employment_status(
            raw,
            job.company_name,
            public_identity_terms,
        )
        if employment_status == "former":
            continue
        annotated = dict(raw)
        annotated["_employment_status"] = employment_status
        annotated["_org_level"] = _classify_org_level(
            annotated.get("title", ""),
            source=annotated.get("source", ""),
            snippet=annotated.get("snippet", ""),
        )
        validated_hiring_team_results.append(annotated)

    bucket_candidate_groups = _dedupe_candidate_bucket_groups(
        {
            "recruiters": _dedupe_candidates(
                recruiter_results,
                [
                    candidate
                    for candidate in validated_hiring_team_results
                    if _classify_person(
                        candidate.get("title", ""),
                        candidate.get("source", ""),
                        candidate.get("snippet", ""),
                    ) == "recruiter"
                ],
            ),
            "hiring_managers": _dedupe_candidates(
                manager_results,
                [
                    candidate
                    for candidate in validated_hiring_team_results
                    if _classify_person(
                        candidate.get("title", ""),
                        candidate.get("source", ""),
                        candidate.get("snippet", ""),
                    ) == "hiring_manager"
                ],
            ),
            "peers": _dedupe_candidates(
                peer_results,
                [
                    candidate
                    for candidate in validated_hiring_team_results
                    if _classify_person(
                        candidate.get("title", ""),
                        candidate.get("source", ""),
                        candidate.get("snippet", ""),
                    ) == "peer"
                ],
            ),
        },
        context=context,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
    )
    recruiter_results = bucket_candidate_groups["recruiters"]
    manager_results = bucket_candidate_groups["hiring_managers"]
    peer_results = bucket_candidate_groups["peers"]
    recruiter_results = _limit_interactive_bucket(
        recruiter_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    manager_results = _limit_interactive_bucket(
        manager_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    peer_results = _limit_interactive_bucket(
        peer_results,
        target_count_per_bucket=target_count_per_bucket,
    )

    bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
    seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}

    store_started_at = time.monotonic()
    for data in recruiter_results:
        person = await _store_person(db, user_id, company, data, "recruiter")
        _append_bucket(
            bucketed,
            seen,
            person,
            data,
            explicit_type="recruiter",
            context=context,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
        )

    for data in manager_results:
        person = await _store_person(
            db,
            user_id,
            company,
            data,
            _classify_person(data.get("title", ""), data.get("source", ""), data.get("snippet", "")),
        )
        _append_bucket(bucketed, seen, person, data, context=context, company_name=job.company_name, public_identity_slugs=public_identity_terms)

    for data in peer_results:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", context=context, company_name=job.company_name, public_identity_slugs=public_identity_terms)
    _record_timing(
        debug,
        stage="store_people",
        started_at=store_started_at,
        recruiter_results=len(recruiter_results),
        manager_results=len(manager_results),
        peer_results=len(peer_results),
    )

    verification_started_at = time.monotonic()
    await verify_people_current_company(
        bucketed,
        company_name=job.company_name,
        company_domain=company.domain if company.domain_trusted else None,
        company_public_identity_slugs=public_identity_terms,
        max_candidates=min(
            _interactive_enrichment_limit_for_target(target_count_per_bucket),
            6,
        ),
    )
    _record_timing(
        debug,
        stage="employment_verification",
        started_at=verification_started_at,
        verify_max_candidates=min(
            _interactive_enrichment_limit_for_target(target_count_per_bucket),
            6,
        ),
    )
    _backfill_sparse_hiring_manager_bucket(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
    )
    warm_paths_started_at = time.monotonic()
    your_connections = await linkedin_graph_service.get_connections_for_company(
        db,
        user_id,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
    )
    direct_connections = await linkedin_graph_service.get_connections_by_linkedin_slugs(
        db,
        user_id,
        _bucketed_linkedin_slugs(bucketed),
    )
    linkedin_graph_service.apply_warm_path_annotations(
        bucketed,
        company_name=job.company_name,
        your_connections=your_connections,
        direct_connections=direct_connections,
        job_title=job.title,
        department=context.department,
    )
    _record_timing(
        debug,
        stage="warm_path_annotations",
        started_at=warm_paths_started_at,
        your_connections=len(your_connections),
        direct_connections=len(direct_connections),
    )
    commit_started_at = time.monotonic()
    await db.commit()
    _record_timing(debug, stage="db_commit", started_at=commit_started_at)

    # Small-company recruiter fallback: when the recruiter bucket is thin
    # (0-1 results) and the company is small/mid-size, promote hiring
    # managers and peers who have an "actively hiring" signal into the
    # recruiter bucket.  At companies with ≤500 employees, engineers and
    # managers often do the recruiting directly.
    company_size_str = (company.size or "").strip().lower()
    _small_company = (
        not company_size_str
        or any(token in company_size_str for token in ("1-", "11-", "51-", "201-", "small", "micro"))
        or (company_size_str.isdigit() and int(company_size_str) <= 500)
    )
    if _small_company and len(bucketed["recruiters"]) <= 1:
        for bucket_name in ("hiring_managers", "peers"):
            for person in bucketed[bucket_name]:
                if len(bucketed["recruiters"]) >= target_count_per_bucket:
                    break
                profile_data = getattr(person, "profile_data", None) or {}
                if profile_data.get("actively_hiring"):
                    identity_key = getattr(person, "linkedin_url", None) or getattr(person, "full_name", "")
                    if identity_key and identity_key not in seen["recruiters"]:
                        setattr(person, "fallback_reason", "Identified as actively hiring on their team (small-company recruiter fallback).")
                        bucketed["recruiters"].append(person)
                        seen["recruiters"].add(identity_key)

    filtered_bucketed = _finalize_bucketed(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
    )
    if debug is not None:
        debug["final"] = {
            "validated_hiring_team_results": [
                _debug_candidate_summary(item)
                for item in validated_hiring_team_results
            ],
            "recruiters": [_debug_person_summary(person) for person in filtered_bucketed["recruiters"]],
            "hiring_managers": [_debug_person_summary(person) for person in filtered_bucketed["hiring_managers"]],
            "peers": [_debug_person_summary(person) for person in filtered_bucketed["peers"]],
        }
        _record_timing(
            debug,
            stage="total",
            started_at=total_started_at,
            final_recruiters=len(filtered_bucketed["recruiters"]),
            final_hiring_managers=len(filtered_bucketed["hiring_managers"]),
            final_peers=len(filtered_bucketed["peers"]),
        )
    return {
        "company": company,
        "your_connections": [
            linkedin_graph_service.serialize_connection(connection)
            for connection in your_connections
        ],
        **filtered_bucketed,
        "job_context": {
            "department": context.department,
            "team_keywords": context.team_keywords,
            "seniority": context.seniority,
        },
        "debug": debug,
    }


async def enrich_person_from_linkedin(
    db: AsyncSession,
    user_id: uuid.UUID,
    linkedin_url: str,
) -> Person:
    """Enrich a single person from LinkedIn via Proxycurl."""
    from app.utils.linkedin import normalize_linkedin_url

    normalized = normalize_linkedin_url(linkedin_url) or linkedin_url

    # Try normalized URL first, fall back to raw URL
    result = await db.execute(
        select(Person).where(Person.user_id == user_id, Person.linkedin_url == normalized)
    )
    existing = result.scalar_one_or_none()
    if not existing and normalized != linkedin_url:
        result = await db.execute(
            select(Person).where(Person.user_id == user_id, Person.linkedin_url == linkedin_url)
        )
        existing = result.scalar_one_or_none()
    if existing and existing.profile_data:
        return existing

    profile = await proxycurl_client.enrich_profile(linkedin_url)

    if existing:
        existing.profile_data = profile
        if profile:
            existing.full_name = profile.get("full_name") or existing.full_name
            existing.title = profile.get("title") or existing.title
        await db.commit()
        await db.refresh(existing)
        return existing

    person_type = _classify_person(profile.get("title", "")) if profile else "peer"
    person = Person(
        user_id=user_id,
        full_name=profile.get("full_name") if profile else None,
        title=profile.get("title") if profile else None,
        linkedin_url=normalized,
        person_type=person_type,
        profile_data=profile,
        source="proxycurl" if profile else "manual",
    )
    db.add(person)
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
