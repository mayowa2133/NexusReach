"""People discovery service for company and job-aware search."""

import asyncio
import copy
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import apollo_client, github_client, proxycurl_client, search_router_client, theorg_client
from app.models.company import Company
from app.models.job import Job
from app.models.person import Person
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
from app.utils.job_context import JobContext, extract_job_context
from app.utils.relevance_scorer import score_candidate_relevance

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
    return min(40, max(10, target_count_per_bucket * 4))


def _prepare_limit_for_target(target_count_per_bucket: int) -> int:
    return min(30, max(6, target_count_per_bucket * 3))


def _minimum_results_for_target(target_count_per_bucket: int) -> int:
    return max(1, min(target_count_per_bucket, 5))


def _count_linkedin_candidates(candidates: list[dict]) -> int:
    return sum(1 for candidate in candidates if candidate.get("linkedin_url"))


def _needs_more_bucket_candidates(candidates: list[dict], *, target_count_per_bucket: int) -> bool:
    return (
        len(candidates) < target_count_per_bucket
        or _count_linkedin_candidates(candidates) < min(target_count_per_bucket, len(candidates))
    )


def _normalize_identity(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _normalize_name_for_matching(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_only.lower()))


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


def _candidate_seniority_level(data: dict) -> str:
    explicit = _normalize_identity(str(data.get("seniority") or ""))
    if explicit in SENIORITY_ORDER:
        return explicit

    haystack = " ".join(
        part for part in [data.get("title", ""), data.get("snippet", "")]
        if part
    ).lower()
    patterns = (
        (r"\bintern\b", "intern"),
        (r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\bassociate\b|\bnew grad\b", "junior"),
        (r"\bsenior\b|\bsr\.?\b", "senior"),
        (r"\bstaff\b", "staff"),
        (r"\bprincipal\b", "principal"),
        (r"\blead\b", "lead"),
        (r"\bmanager\b", "manager"),
        (r"\bdirector\b", "director"),
        (r"\bvp\b|\bvice president\b", "vp"),
        (r"\bchief\b|\bc-level\b", "executive"),
    )
    for pattern, level in patterns:
        if re.search(pattern, haystack):
            return level
    return "mid"


def _seniority_fit_rank(data: dict, *, bucket: str, context: JobContext | None) -> int:
    if not context:
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
    - Company verification (0-30 pts)
    - Team/department relevance (0-25 pts)
    - Title/role fit for bucket (0-20 pts)
    - Seniority match (0-15 pts)
    - LinkedIn profile presence (0-5 pts)
    - Source quality (0-5 pts)
    """
    score = 0

    # --- Company verification (0-30) ---
    employment_status = data.get("_employment_status")
    if not employment_status:
        employment_status = _classify_employment_status(data, company_name, public_identity_slugs)
    if employment_status == "current":
        trusted = _trusted_public_match(data, company_name, public_identity_slugs)
        source = data.get("source", "")
        if source in CURRENT_TRUSTED_SOURCES or trusted:
            score += 30
        else:
            score += 25
    elif employment_status == "ambiguous":
        score += 12
    # former gets 0

    # --- Team/department relevance (0-25) ---
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
            score += 25
        elif team_keyword_hits == 1:
            score += 18
        elif context.department.replace("_", " ") in haystack:
            score += 12
        else:
            score += 4
    else:
        score += 12  # no context = neutral

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

    # --- Seniority match (0-15) ---
    seniority_rank = _seniority_fit_rank(data, bucket=bucket, context=context)
    if seniority_rank == 0:
        score += 15
    elif seniority_rank == 1:
        score += 10
    else:
        score += 4

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
    texts = [data.get("snippet", ""), data.get("title", "")]
    patterns = [
        rf"\b(?:currently serving as|serving as|works as|working as|is)\s+(?:an?\s+)?(?P<title>[^.;|,\n]+?)\s+(?:at|@)\s+{company_pattern}\b",
        rf"\b(?P<title>[^.;|,\n]+?)\s*@\s*{company_pattern}\b",
        rf"\b(?P<title>[^.;|,\n]+?)\s+at\s+{company_pattern}\b",
    ]

    for text in texts:
        normalized = " ".join((text or "").split())
        if not normalized:
            continue
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


def _linkedin_backfill_search_titles(candidate: dict, *, bucket: str, company_name: str) -> list[str]:
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
        titles.extend(
            [
                "engineering manager",
                "software engineering manager",
                "director engineering",
                "senior director engineering",
            ]
        )
    elif bucket == "peers":
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
) -> list[dict]:
    backfilled: list[dict] = []
    for raw in candidates:
        data = dict(raw)
        if data.get("linkedin_url"):
            backfilled.append(data)
            continue

        public_url = _public_profile_url(data)
        if not public_url:
            backfilled.append(data)
            continue

        employment_status = data.get("_employment_status") or _classify_employment_status(
            data,
            company_name,
            public_identity_slugs,
        )
        trusted_public = _trusted_public_match(data, company_name, public_identity_slugs)
        if employment_status != "current" and not trusted_public:
            data["profile_data"] = _linkedin_backfill_metadata(data, status="skipped")
            backfilled.append(data)
            continue

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
        matches = await search_router_client.search_exact_linkedin_profile(
            data.get("full_name", ""),
            company_name,
            name_variants=exact_name_variants,
            title_hints=exact_title_hints,
            team_keywords=exact_team_keywords,
            limit=5,
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
                    limit=8,
                    min_results=1,
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
        backfilled.append(data)
    return backfilled


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
    company_domain: str | None = None,
    limit: int,
    min_results: int,
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
        public_identity_terms=public_identity_terms,
        company_domain=company_domain,
        limit=limit,
        min_results=max(1, min_results),
    )
    return _dedupe_candidates(existing_candidates, retry_candidates)


def _public_url_matches_company(public_url: str, company_name: str) -> bool:
    if not public_url:
        return False
    return _slugify(company_name) in urlparse(public_url).path.lower()


def _trusted_public_match(data: dict, company_name: str, public_identity_slugs: list[str] | None = None) -> bool:
    public_url = _public_profile_url(data)
    return matches_public_company_identity(public_url, company_name, public_identity_slugs)


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
    if any(keyword in haystack for keyword in MANAGER_TITLE_KEYWORDS):
        return "manager"
    if any(keyword in haystack for keyword in CONTROLLED_LEAD_KEYWORDS):
        return "manager"
    return "ic"


def _source_rank(source: str | None) -> int:
    return SOURCE_PRIORITY.get(source or "", 5)


def _org_rank(bucket: str, org_level: str) -> int:
    if bucket == "hiring_managers":
        return {"manager": 0, "director_plus": 1, "ic": 2}.get(org_level, 3)
    if bucket == "recruiters":
        return {"ic": 0, "manager": 1, "director_plus": 2}.get(org_level, 3)
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


def _candidate_sort_key(data: dict, *, bucket: str, context: JobContext | None) -> tuple:
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    if bucket == "recruiters":
        explicit_role_rank = 0 if _is_recruiter_like(title) else 1 if _is_recruiter_like(snippet) else 2
    elif bucket == "hiring_managers":
        manager_keywords = MANAGER_TITLE_KEYWORDS + CONTROLLED_LEAD_KEYWORDS
        explicit_role_rank = 0 if _contains_any_keyword(title, manager_keywords) else 1 if _contains_any_keyword(snippet, manager_keywords) else 2
    else:
        explicit_role_rank = 0
    team_rank = _team_keyword_match_rank(data, bucket=bucket, context=context) if bucket == "hiring_managers" else 1
    return (
        _org_rank(bucket, data.get("_org_level", "ic")),
        team_rank,
        _source_rank(data.get("source")),
        _context_rank(data, context),
        _seniority_fit_rank(data, bucket=bucket, context=context),
        explicit_role_rank,
        1 if data.get("_weak_title") else 0,
        0 if _role_like_title(title) else 1,
        _normalize_identity(data.get("full_name")),
    )


def _allow_director_plus(context: JobContext | None) -> bool:
    return bool(context and context.seniority in SENIOR_MANAGER_LEVELS)


def _manager_seniority_filters(context: JobContext | None) -> list[str]:
    if context and getattr(context, "early_career", False):
        return ["manager"]
    if context and context.seniority in {"intern", "junior"}:
        return ["manager"]
    return ["manager", "director", "vp"]


def _prepare_candidates(
    candidates: list[dict],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
    bucket: str,
    context: JobContext | None,
    limit: int,
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

    for raw in candidates:
        data = dict(raw)
        title = data.get("title", "") or ""
        snippet = data.get("snippet", "") or ""
        weak_title = data.get("_weak_title")
        if weak_title is None:
            weak_title = _title_is_weak(title, company_name)
            data["_weak_title"] = weak_title
        if (
            bucket == "peers"
            and data.get("source") in PUBLIC_WEB_SOURCES
            and not _trusted_public_match(data, company_name, public_identity_slugs)
        ):
            continue
        if bucket in {"recruiters", "hiring_managers"} and weak_title:
            # For ambiguous companies, weak titles from broad search may still
            # be real employees — include as low-priority fallbacks in peers bucket
            # instead of silently dropping them
            continue
        if not _candidate_matches_company(data, company_name, public_identity_slugs):
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
                continue
        if bucket == "recruiters":
            if not (
                _is_recruiter_like(title)
                or _is_recruiter_like(snippet)
            ):
                continue
            if title and not (
                _is_recruiter_like(title)
                or _role_like_title(title)
            ):
                continue
        if bucket == "hiring_managers" and title and not (
            _is_manager_like(title)
            or _role_like_title(title)
        ):
            continue

        employment_status = _classify_employment_status(data, company_name, public_identity_slugs)
        if employment_status == "former":
            continue

        org_level = _classify_org_level(
            data.get("title", ""),
            source=data.get("source", ""),
            snippet=data.get("snippet", ""),
        )

        if bucket == "hiring_managers" and org_level == "ic" and not senior_ic_fallback:
            continue
        if bucket == "peers" and org_level == "director_plus":
            continue

        is_fallback = False
        if bucket == "hiring_managers" and org_level == "director_plus" and not _allow_director_plus(context):
            is_fallback = True
        if bucket == "recruiters" and org_level == "director_plus":
            is_fallback = True
        if senior_ic_fallback:
            is_fallback = True

        data["_employment_status"] = employment_status
        data["_org_level"] = org_level
        data["_director_fallback"] = is_fallback
        data["_senior_ic_fallback"] = senior_ic_fallback

        if employment_status == "current":
            (current_fallback if is_fallback else current_primary).append(data)
        else:
            (ambiguous_fallback if is_fallback else ambiguous_primary).append(data)

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


def _classify_person(title: str, source: str = "", snippet: str = "") -> str:
    """Classify a result into recruiter, hiring_manager, or peer."""
    haystack = " ".join(part for part in [title, snippet, source] if part).lower()
    if _is_recruiter_like(haystack):
        return "recruiter"
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


def _candidate_bucket_assignment_rank(
    bucket: str,
    data: dict,
    *,
    context: JobContext | None,
    company_name: str = "",
    public_identity_slugs: list[str] | None = None,
) -> tuple[int, int, int, int, int, int, str]:
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
    public_identity_terms: list[str] | None = None,
    company_domain: str | None = None,
    limit: int = 5,
    min_results: int = 2,
) -> list[dict]:
    """Run Apollo plus routed SERP/public search with dedupe."""
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

    brave_results = []
    merged = _dedupe_candidates(apollo_filtered, apollo_unfiltered)
    if len(merged) < min_results:
        brave_results = await search_router_client.search_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            limit=max(limit, 5),
            min_results=min_results,
            company_domain=company_domain,
        )

    public_results = []
    merged = _dedupe_candidates(merged, brave_results)
    if len(merged) < min_results or is_ambiguous_company_name(company_name) or bool(public_identity_terms):
        public_results = await search_router_client.search_public_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            public_identity_terms=public_identity_terms,
            limit=max(limit, 5),
            min_results=min_results,
        )

    deduped = _dedupe_candidates(apollo_filtered, apollo_unfiltered, brave_results, public_results)
    return deduped[: max(limit, 8)]


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
    seen: dict[str, set[uuid.UUID]],
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
    if person.id in seen[bucket_name]:
        return
    seen[bucket_name].add(person.id)
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


def _dedupe_bucket_assignments(bucketed: dict[str, list[Person]]) -> dict[str, list[Person]]:
    winners: dict[uuid.UUID, tuple[str, tuple[int, int, int, int, int, str]]] = {}
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
                _confidence_rank(getattr(person, "company_match_confidence", None)),
                -(getattr(person, "usefulness_score", None) or 0),
                _match_rank(getattr(person, "match_quality", None)),
                _org_rank(bucket, getattr(person, "org_level", "ic") or "ic"),
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
        ),
        _search_candidates(
            company_name,
            titles=manager_titles,
            seniority=["manager", "director", "vp"],
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
        ),
        _search_candidates(
            company_name,
            titles=peer_titles,
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
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

    return {"company": company, **finalized}


async def search_people_for_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    min_relevance_score: int = 1,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
) -> dict:
    """Find people at a company using extracted job context."""
    target_count_per_bucket = _clamp_target_count_per_bucket(target_count_per_bucket)
    search_limit = _search_limit_for_target(target_count_per_bucket)
    prepare_limit = _prepare_limit_for_target(target_count_per_bucket)
    minimum_results = _minimum_results_for_target(target_count_per_bucket)

    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    context = extract_job_context(job.title, job.description)
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
            # domain_root is useless when it equals the company name (e.g. "ivo" for Ivo)
            dr = (hints.get("domain_root") or "").strip().lower()
            if dr and dr != normalized:
                search_domain = dr
            if not search_domain:
                # Derive domain from linkedin_company_slug (e.g. "ivoai" → "ivo.ai")
                li_slug = (hints.get("linkedin_company_slug") or "").strip().lower()
                if li_slug and li_slug != normalized:
                    # Try to extract a dotted domain from slug (e.g. "ivoai" with name "ivo" → "ivo.ai")
                    common_tlds = ("ai", "io", "co", "app", "dev", "tech", "xyz", "com", "org", "net")
                    derived_domain = None
                    if li_slug.startswith(normalized):
                        suffix = li_slug[len(normalized):]
                        if suffix in common_tlds:
                            derived_domain = f"{normalized}.{suffix}"
                    search_domain = derived_domain or li_slug
            if not search_domain:
                # careers_host only useful if not a generic ATS host
                ch = (hints.get("careers_host") or "").strip().lower()
                if ch and not any(root in ch for root in ("lever", "greenhouse", "ashby", "workable", "workday")):
                    search_domain = ch

    recruiter_min_results = minimum_results
    manager_min_results = minimum_results
    peer_min_results = minimum_results
    recruiter_titles = _prioritize_titles_for_search(
        context.recruiter_titles,
        bucket="recruiters",
        context=context,
    )
    manager_titles = _prioritize_titles_for_search(
        context.manager_titles,
        bucket="hiring_managers",
        context=context,
    )
    peer_titles = _prioritize_titles_for_search(
        context.peer_titles,
        bucket="peers",
        context=context,
    )

    recruiter_candidates = await _search_candidates(
        job.company_name,
        titles=recruiter_titles,
        departments=context.apollo_departments,
        team_keywords=context.team_keywords + context.domain_keywords,
        public_identity_terms=public_identity_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=recruiter_min_results,
    )
    manager_candidates = await _search_candidates(
        job.company_name,
        titles=manager_titles,
        departments=context.apollo_departments,
        seniority=_manager_seniority_filters(context),
        team_keywords=context.team_keywords + context.domain_keywords,
        public_identity_terms=public_identity_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=manager_min_results,
    )
    peer_candidates = await _search_candidates(
        job.company_name,
        titles=peer_titles,
        departments=context.apollo_departments,
        team_keywords=context.team_keywords + context.domain_keywords,
        public_identity_terms=public_identity_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=peer_min_results,
    )
    # For ambiguous companies, run a broad employee discovery without title constraints
    # since title-specific queries get polluted by people sharing the company name
    if search_domain and is_ambiguous_company_name(job.company_name):
        broad_employees = await search_router_client.search_people(
            job.company_name,
            titles=None,
            team_keywords=None,
            limit=max(search_limit, 15),
            min_results=5,
            company_domain=search_domain,
        )
        recruiter_candidates = _dedupe_candidates(recruiter_candidates, broad_employees)
        manager_candidates = _dedupe_candidates(manager_candidates, broad_employees)
        peer_candidates = _dedupe_candidates(peer_candidates, broad_employees)

    hiring_team_candidates = await search_router_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=max(5, min(target_count_per_bucket + 2, 8)),
        min_results=1,
    )
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
    peer_candidates = await _expand_peer_candidates(
        job.company_name,
        peer_candidates,
        context=context,
        public_identity_terms=public_identity_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=max(peer_min_results, target_count_per_bucket),
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

    manager_candidates = await _score_contextual_candidates(
        manager_candidates,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
    )
    peer_candidates = await _score_contextual_candidates(
        peer_candidates,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
    )
    recruiter_results = _prepare_candidates(
        recruiter_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="recruiters",
        context=context,
        limit=prepare_limit,
    )
    manager_results = _prepare_candidates(
        manager_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
        context=context,
        limit=prepare_limit,
    )
    peer_results = _prepare_candidates(
        peer_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
        context=context,
        limit=prepare_limit,
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
        )
        manager_results = _prepare_candidates(
            _dedupe_candidates(manager_candidates, theorg_candidates.get("hiring_managers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=context,
            limit=prepare_limit,
        )
        peer_results = _prepare_candidates(
            _dedupe_candidates(peer_candidates, theorg_candidates.get("peers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=context,
            limit=prepare_limit,
        )

    recruiter_results = await _backfill_linkedin_profiles(
        recruiter_results,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="recruiters",
    )
    manager_results = await _backfill_linkedin_profiles(
        manager_results,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
    )
    peer_results = await _backfill_linkedin_profiles(
        peer_results,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
    )

    if any(
        _needs_more_bucket_candidates(results, target_count_per_bucket=target_count_per_bucket)
        for results in (recruiter_results, manager_results, peer_results)
    ):
        if _needs_more_bucket_candidates(recruiter_results, target_count_per_bucket=target_count_per_bucket):
            recruiter_candidates = _dedupe_candidates(
                recruiter_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_recruiter_titles(context),
                    departments=context.apollo_departments,
                    team_keywords=None,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=recruiter_min_results,
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
            )
            recruiter_results = await _backfill_linkedin_profiles(
                recruiter_results,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="recruiters",
            )

        if _needs_more_bucket_candidates(manager_results, target_count_per_bucket=target_count_per_bucket):
            manager_candidates = _dedupe_candidates(
                manager_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_manager_titles(context),
                    departments=context.apollo_departments,
                    seniority=_manager_seniority_filters(context),
                    team_keywords=None,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=manager_min_results,
                ),
            )
            manager_candidates = await _recover_candidate_titles(
                manager_candidates,
                company=company,
                company_name=job.company_name,
            )
            manager_candidates = await _score_contextual_candidates(
                manager_candidates,
                job=job,
                context=context,
                min_relevance_score=min_relevance_score,
            )
            manager_results = _prepare_candidates(
                manager_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
                context=context,
                limit=prepare_limit,
            )
            manager_results = await _backfill_linkedin_profiles(
                manager_results,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
            )

        if _needs_more_bucket_candidates(peer_results, target_count_per_bucket=target_count_per_bucket):
            peer_candidates = _dedupe_candidates(
                peer_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_peer_titles(context),
                    departments=context.apollo_departments,
                    team_keywords=None,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=peer_min_results,
                ),
            )
            peer_candidates = await _recover_candidate_titles(
                peer_candidates,
                company=company,
                company_name=job.company_name,
            )
            peer_candidates = await _score_contextual_candidates(
                peer_candidates,
                job=job,
                context=context,
                min_relevance_score=min_relevance_score,
            )
            peer_results = _prepare_candidates(
                peer_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
                context=context,
                limit=prepare_limit,
            )
            peer_results = await _backfill_linkedin_profiles(
                peer_results,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
            )

    hiring_team_results = await search_router_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=max(3, min(target_count_per_bucket + 1, 6)),
        min_results=1,
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

    bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
    seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}

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

    await verify_people_current_company(
        bucketed,
        company_name=job.company_name,
        company_domain=company.domain if company.domain_trusted else None,
        company_public_identity_slugs=public_identity_terms,
    )
    _backfill_sparse_hiring_manager_bucket(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
    )
    await db.commit()
    filtered_bucketed = _finalize_bucketed(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
    )
    return {
        "company": company,
        **filtered_bucketed,
        "job_context": {
            "department": context.department,
            "team_keywords": context.team_keywords,
            "seniority": context.seniority,
        },
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
