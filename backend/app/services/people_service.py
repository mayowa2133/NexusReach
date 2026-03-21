"""People discovery service for company and job-aware search."""

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import apollo_client, brave_search_client, github_client, proxycurl_client, theorg_client
from app.models.company import Company
from app.models.job import Job
from app.models.person import Person
from app.services.employment_verification_service import verify_people_current_company
from app.services.theorg_discovery_service import discover_theorg_candidates
from app.utils.company_identity import (
    build_public_identity_hints,
    canonical_company_display_name,
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
    "recruiting",
    "recruiting coordinator",
    "recruiting partner",
    "talent acquisition",
    "talent partner",
    "sourcer",
    "technical sourcer",
    "campus recruiter",
    "university recruiter",
    "early careers",
    "early talent",
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
}
CURRENT_TRUSTED_PUBLIC_HOSTS = {
    "theorg.com",
    "www.theorg.com",
}
SOURCE_PRIORITY = {
    "apollo": 0,
    "proxycurl": 1,
    "brave_hiring_team": 1,
    "theorg_traversal": 2,
    "brave_search": 3,
    "brave_public_web": 4,
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


def _normalize_identity(value: str | None) -> str:
    return " ".join((value or "").lower().split())


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
        keyword in normalized for keyword in ("recruit", "talent acquisition", "talent partner", "sourcer", "early talent", "early careers", "university")
    )
    return not generic_only


def _is_manager_like(text: str | None) -> bool:
    normalized = _normalize_identity(text)
    if not normalized:
        return False
    return _contains_any_keyword(normalized, MANAGER_TITLE_KEYWORDS + CONTROLLED_LEAD_KEYWORDS)


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
    for slug in slugs:
        clean = (slug or "").strip().lower()
        if clean and is_compatible_public_identity_slug(company_name, clean):
            merged.add(clean)
    company.public_identity_slugs = sorted(merged)

    hints = company.identity_hints if isinstance(company.identity_hints, dict) else {}
    theorg_hints = hints.setdefault("theorg", {})
    if preferred_slug:
        theorg_hints["preferred_org_slug"] = preferred_slug
    if preferred_slug and preferred_status:
        slug_status = theorg_hints.setdefault("slug_status", {})
        slug_status[preferred_slug] = preferred_status
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
    company_name: str,
) -> tuple[str, int, str, str] | None:
    public_url = _public_profile_url(data)
    if not public_url:
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
    public_url = _public_profile_url(data)
    host = _public_profile_host(data)
    company_mentioned = (
        _mentions_company(title, company_name)
        or _mentions_company(snippet, company_name)
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
    if data.get("source") == "brave_public_web" and any(term in combined_text for term in PUBLIC_DIRECTORY_TERMS):
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
    return (
        _org_rank(bucket, data.get("_org_level", "ic")),
        _source_rank(data.get("source")),
        _context_rank(data, context),
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
            and data.get("source") == "brave_public_web"
            and not _trusted_public_match(data, company_name, public_identity_slugs)
        ):
            continue
        if bucket in {"recruiters", "hiring_managers"} and weak_title:
            continue
        if not _candidate_matches_company(data, company_name, public_identity_slugs):
            continue

        person_type = _classify_person(
            title,
            source=data.get("source", ""),
            snippet=snippet,
        )
        if person_type != expected_type:
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

        if bucket == "hiring_managers" and org_level == "ic":
            continue
        if bucket == "peers" and org_level == "director_plus":
            continue

        is_fallback = False
        if bucket == "hiring_managers" and org_level == "director_plus" and not _allow_director_plus(context):
            is_fallback = True
        if bucket == "recruiters" and org_level == "director_plus":
            is_fallback = True

        data["_employment_status"] = employment_status
        data["_org_level"] = org_level
        data["_director_fallback"] = is_fallback

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
    minimum_per_bucket: int = 2,
) -> bool:
    if is_ambiguous_company_name(company_name):
        return True
    if context and getattr(context, "early_career", False):
        targets = {"recruiters": 3, "hiring_managers": 1, "peers": 1}
        return any(current_counts.get(bucket, 0) < target for bucket, target in targets.items())
    return any(count < minimum_per_bucket for count in current_counts.values())


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

    if person_type == "recruiter":
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
            return "next_best", f"Adjacent {department_label} manager at the target company."
        return "next_best", f"Adjacent {department_label} teammate at the target company."

    if person_type == "hiring_manager":
        return "direct", "Relevant manager title at the target company."
    if person_type == "peer":
        return "direct", "Relevant teammate title at the target company."
    return "direct", None


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
        if slug:
            candidates.append(slug)
    return list(dict.fromkeys(candidates))


def _candidate_theorg_slug_candidates(*groups: list[dict]) -> list[str]:
    slugs: list[str] = []
    for group in groups:
        for candidate in group:
            slug = _candidate_public_identity_slug(candidate)
            if slug:
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
    limit: int = 5,
    min_results: int = 2,
) -> list[dict]:
    """Run Apollo -> Brave LinkedIn -> Brave public-web search with dedupe."""
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
        brave_results = await brave_search_client.search_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            limit=max(limit, 5),
        )

    public_results = []
    merged = _dedupe_candidates(merged, brave_results)
    if len(merged) < min_results or is_ambiguous_company_name(company_name) or bool(public_identity_terms):
        public_results = await brave_search_client.search_public_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            public_identity_terms=public_identity_terms,
            limit=max(limit, 5),
        )

    if is_ambiguous_company_name(company_name) or bool(public_identity_terms):
        deduped = _dedupe_candidates(apollo_filtered, apollo_unfiltered, public_results, brave_results)
    else:
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
            careers_url=getattr(company, "careers_url", None) or (company_data or {}).get("careers_url"),
            linkedin_company_url=(company_data or {}).get("linkedin_url"),
        )
        company.public_identity_slugs = identity_bundle.slugs
        company.identity_hints = identity_bundle.hints
        if company_data and not getattr(company, "careers_url", None):
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
        careers_url=(company_data or {}).get("careers_url"),
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
        careers_url=company_data.get("careers_url") if company_data else None,
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
    linkedin = data.get("linkedin_url", "")
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
            if not existing.title and data.get("title"):
                existing.title = data.get("title")
            if not existing.full_name and data.get("full_name"):
                existing.full_name = data.get("full_name")
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
            if not existing.title and data.get("title"):
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

    if not linkedin and not apollo_id and data.get("full_name") and data.get("title"):
        result = await db.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.company_id == company_id,
                Person.full_name == data.get("full_name"),
                Person.title == data.get("title"),
            )
        )
        existing = result.scalars().first()
        if existing:
            if company:
                existing.company = company
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

    setattr(person, "match_quality", match_quality)
    setattr(person, "match_reason", match_reason)
    setattr(person, "employment_status", employment_status)
    setattr(person, "org_level", org_level)


def _append_bucket(
    bucketed: dict[str, list[Person]],
    seen: dict[str, set[uuid.UUID]],
    person: Person,
    data: dict,
    explicit_type: str | None = None,
    context: JobContext | None = None,
    company_name: str | None = None,
) -> None:
    person_type = explicit_type or _classify_person(
        person.title or data.get("title", ""),
        source=data.get("source", ""),
        snippet=data.get("snippet", ""),
    )
    person.person_type = person_type
    _apply_match_metadata(person, data, person_type, context, company_name=company_name)

    bucket_name = {
        "recruiter": "recruiters",
        "hiring_manager": "hiring_managers",
        "peer": "peers",
    }[person_type]
    if person.id in seen[bucket_name]:
        return
    seen[bucket_name].add(person.id)
    bucketed[bucket_name].append(person)


def _filter_verified_bucketed(bucketed: dict[str, list[Person]]) -> dict[str, list[Person]]:
    filtered: dict[str, list[Person]] = {}
    for bucket, people in bucketed.items():
        filtered[bucket] = [person for person in people if person.current_company_verified is True]
    return filtered


async def search_people_at_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
    roles: list[str] | None = None,
    github_org: str | None = None,
) -> dict:
    """Find people at a company using company-level search."""
    company = await get_or_create_company(db, user_id, company_name)
    public_identity_terms = company.public_identity_slugs or None

    recruiter_titles = [
        "technical recruiter",
        "engineering recruiter",
        "talent acquisition",
        "technical sourcer",
        "talent acquisition partner",
        "recruiting coordinator",
    ]
    manager_titles = roles or ["engineering manager", "technical lead", "team lead"]
    peer_titles = roles or ["software engineer", "backend engineer", "developer"]

    recruiter_candidates = await _search_candidates(
        company_name,
        titles=recruiter_titles,
        public_identity_terms=public_identity_terms,
        limit=10,
    )
    manager_candidates = await _search_candidates(
        company_name,
        titles=manager_titles,
        seniority=["manager", "director", "vp"],
        public_identity_terms=public_identity_terms,
        limit=10,
    )
    peer_candidates = await _search_candidates(
        company_name,
        titles=peer_titles,
        public_identity_terms=public_identity_terms,
        limit=10,
    )
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
        )
        + saved_slug_candidates,
    )
    public_identity_terms = company.public_identity_slugs or None

    recruiter_candidates = await _recover_candidate_titles(
        recruiter_candidates,
        company=company,
        company_name=company_name,
    )
    manager_candidates = await _recover_candidate_titles(
        manager_candidates,
        company=company,
        company_name=company_name,
    )
    peer_candidates = await _recover_candidate_titles(
        peer_candidates,
        company=company,
        company_name=company_name,
    )

    recruiter_results = _prepare_candidates(
        recruiter_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="recruiters",
        context=None,
        limit=5,
    )
    manager_results = _prepare_candidates(
        manager_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
        context=None,
        limit=5,
    )
    peer_results = _prepare_candidates(
        peer_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
        context=None,
        limit=5,
    )

    if _should_expand_with_theorg(
        company_name,
        {
            "recruiters": len(recruiter_results),
            "hiring_managers": len(manager_results),
            "peers": len(peer_results),
        },
        context=None,
    ):
        theorg_candidates = await discover_theorg_candidates(
            company,
            company_name=company_name,
            context=None,
            current_counts={
                "recruiters": len(recruiter_results),
                "hiring_managers": len(manager_results),
                "peers": len(peer_results),
            },
            slug_candidates=_candidate_theorg_slug_candidates(
                recruiter_candidates,
                manager_candidates,
                peer_candidates,
            )
            + saved_slug_candidates,
        )
        recruiter_results = _prepare_candidates(
            _dedupe_candidates(recruiter_candidates, theorg_candidates.get("recruiters", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=None,
            limit=5,
        )
        manager_results = _prepare_candidates(
            _dedupe_candidates(manager_candidates, theorg_candidates.get("hiring_managers", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=None,
            limit=5,
        )
        peer_results = _prepare_candidates(
            _dedupe_candidates(peer_candidates, theorg_candidates.get("peers", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=None,
            limit=5,
        )

    github_members: list[dict] = []
    if github_org:
        github_members = await github_client.search_org_members(github_org, limit=5)
        for member in github_members:
            repos = await github_client.get_user_repos(member["login"], limit=3)
            languages = list({repo["language"] for repo in repos if repo.get("language")})
            member["github_data"] = {"repos": repos, "languages": languages}
            member["github_url"] = member.get("github_url", "")

    bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
    seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}

    for data in recruiter_results:
        person = await _store_person(db, user_id, company, data, "recruiter")
        _append_bucket(bucketed, seen, person, data, explicit_type="recruiter", company_name=company_name)

    for data in manager_results:
        person = await _store_person(
            db,
            user_id,
            company,
            data,
            _classify_person(data.get("title", "")),
        )
        _append_bucket(bucketed, seen, person, data, company_name=company_name)

    for data in peer_results:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", company_name=company_name)

    for data in github_members:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer")

    await verify_people_current_company(
        bucketed,
        company_name=company_name,
        company_domain=company.domain if company.domain_trusted else None,
        company_public_identity_slugs=company.public_identity_slugs,
    )
    await db.commit()
    return {"company": company, **_filter_verified_bucketed(bucketed)}


async def search_people_for_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    min_relevance_score: int = 1,
) -> dict:
    """Find people at a company using extracted job context."""
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    context = extract_job_context(job.title, job.description)
    company = await get_or_create_company(db, user_id, job.company_name, ats_slug=job.ats_slug)
    public_identity_terms = company.public_identity_slugs or None
    recruiter_min_results = 3 if context.early_career else 2
    manager_min_results = 2
    peer_min_results = 1 if context.early_career else 2
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
        limit=10,
        min_results=recruiter_min_results,
    )
    manager_candidates = await _search_candidates(
        job.company_name,
        titles=manager_titles,
        departments=context.apollo_departments,
        seniority=_manager_seniority_filters(context),
        team_keywords=context.team_keywords + context.domain_keywords,
        public_identity_terms=public_identity_terms,
        limit=10,
        min_results=manager_min_results,
    )
    peer_candidates = await _search_candidates(
        job.company_name,
        titles=peer_titles,
        departments=context.apollo_departments,
        team_keywords=context.team_keywords + context.domain_keywords,
        public_identity_terms=public_identity_terms,
        limit=10,
        min_results=peer_min_results,
    )
    hiring_team_candidates = await brave_search_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=5,
    )
    recruiter_candidates = _dedupe_candidates(
        recruiter_candidates,
        [candidate for candidate in hiring_team_candidates if _classify_person(candidate.get("title", ""), snippet=candidate.get("snippet", ""), source=candidate.get("source", "")) == "recruiter"],
    )
    manager_candidates = _dedupe_candidates(
        manager_candidates,
        [candidate for candidate in hiring_team_candidates if _classify_person(candidate.get("title", ""), snippet=candidate.get("snippet", ""), source=candidate.get("source", "")) == "hiring_manager"],
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
        )
        + saved_slug_candidates,
    )
    public_identity_terms = company.public_identity_slugs or None

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
        limit=5,
    )
    manager_results = _prepare_candidates(
        manager_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
        context=context,
        limit=5,
    )
    peer_results = _prepare_candidates(
        peer_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
        context=context,
        limit=5,
    )

    if _should_expand_with_theorg(
        job.company_name,
        {
            "recruiters": len(recruiter_results),
            "hiring_managers": len(manager_results),
            "peers": len(peer_results),
        },
        context=context,
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
            )
            + saved_slug_candidates,
        )
        recruiter_results = _prepare_candidates(
            _dedupe_candidates(recruiter_candidates, theorg_candidates.get("recruiters", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=context,
            limit=5,
        )
        manager_results = _prepare_candidates(
            _dedupe_candidates(manager_candidates, theorg_candidates.get("hiring_managers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=context,
            limit=5,
        )
        peer_results = _prepare_candidates(
            _dedupe_candidates(peer_candidates, theorg_candidates.get("peers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=context,
            limit=5,
        )

    hiring_team_results = await brave_search_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=3,
    )

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
        )

    for data in manager_results:
        person = await _store_person(
            db,
            user_id,
            company,
            data,
            _classify_person(data.get("title", ""), data.get("source", ""), data.get("snippet", "")),
        )
        _append_bucket(bucketed, seen, person, data, context=context, company_name=job.company_name)

    for data in peer_results:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", context=context, company_name=job.company_name)

    for data in hiring_team_results:
        if not _candidate_matches_company(data, job.company_name, public_identity_terms):
            continue
        if _classify_employment_status(data, job.company_name, public_identity_terms) == "former":
            continue
        data["_employment_status"] = _classify_employment_status(
            data,
            job.company_name,
            public_identity_terms,
        )
        data["_org_level"] = _classify_org_level(
            data.get("title", ""),
            source=data.get("source", ""),
            snippet=data.get("snippet", ""),
        )
        person = await _store_person(
            db,
            user_id,
            company,
            data,
            _classify_person(data.get("title", ""), data.get("source", ""), data.get("snippet", "")),
        )
        _append_bucket(bucketed, seen, person, data, context=context, company_name=job.company_name)

    await verify_people_current_company(
        bucketed,
        company_name=job.company_name,
        company_domain=company.domain if company.domain_trusted else None,
        company_public_identity_slugs=company.public_identity_slugs,
    )
    await db.commit()
    filtered_bucketed = _filter_verified_bucketed(bucketed)
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
        linkedin_url=linkedin_url,
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
) -> list[Person]:
    """Get all saved people for a user, optionally filtered by company."""
    query = select(Person).options(selectinload(Person.company)).where(Person.user_id == user_id)
    if company_id:
        query = query.where(Person.company_id == company_id)
    query = query.order_by(Person.created_at.desc())

    result = await db.execute(query)
    people = list(result.scalars().all())
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
    return people
