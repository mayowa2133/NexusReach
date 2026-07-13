"""Job-context geo signals and roles-context construction for people discovery."""

import logging
import re


from app.utils.job_context import (
    APOLLO_DEPARTMENT_SLUGS,
    JobContext,
)
from app.services.occupation_taxonomy import (
    classify_title,
    manager_title_seeds_for,
    occupations_for_keys,
    peer_title_seeds_for,
)

from app.services.people.identity import _dedupe_text, _keyword_in_text
from app.services.people.titles import _is_manager_like, _is_recruiter_like
logger = logging.getLogger(__name__)


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


def _build_roles_context(roles: list[str] | None) -> JobContext | None:
    """Build a lightweight JobContext from user-provided roles for ranking.

    Extracts team keywords from role titles (e.g. "Engineering Manager" → "engineering")
    so that candidate ranking can prefer relevant managers over random directors.
    """
    if not roles:
        return None

    # Resolve the same canonical taxonomy used by job discovery. Company-level
    # people search previously guessed only product/data/marketing and silently
    # defaulted every other explicit role to engineering.
    occupation_keys: list[str] = []
    for role in roles:
        for key in classify_title(role):
            if key not in occupation_keys:
                occupation_keys.append(key)
    occupations = occupations_for_keys(occupation_keys)

    # Extract meaningful keywords from role titles.
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

    if not team_keywords and not occupations:
        return None

    # Unknown roles stay neutral instead of becoming engineering.
    department = occupations[0].department_bucket if occupations else ""
    apollo_bucket = {
        "engineering": "engineering",
        "ml_ai": "data_science",
        "data": "data_science",
        "product": "product_management",
        "design": "design",
        "marketing": "marketing",
        "sales": "sales",
        "customer_success": "customer_success",
        "finance": "finance",
        "people": "human_resources",
        "legal": "legal",
        "business": "operations",
        "consulting": "operations",
        "program_management": "operations",
        "supply_chain": "operations",
        "information_technology": "information_technology",
        "security": "information_technology",
    }.get(department)
    apollo_departments = (
        APOLLO_DEPARTMENT_SLUGS.get(apollo_bucket, []) if apollo_bucket else []
    )

    # Determine appropriate seniority level
    seniority = "mid"
    if early_career:
        has_intern = any("intern" in r.lower() for r in roles)
        seniority = "intern" if has_intern else "junior"

    taxonomy_managers = manager_title_seeds_for(occupation_keys)
    taxonomy_peers = peer_title_seeds_for(occupation_keys)
    explicit_managers = [
        role for role in roles if _is_manager_like(role) and not _is_recruiter_like(role)
    ]
    explicit_peers = [
        role for role in roles if not _is_manager_like(role) and not _is_recruiter_like(role)
    ]
    explicit_recruiters = [role for role in roles if _is_recruiter_like(role)]

    return JobContext(
        department=department,
        team_keywords=team_keywords,
        domain_keywords=[],
        seniority=seniority,
        early_career=early_career,
        manager_titles=list(dict.fromkeys(explicit_managers + taxonomy_managers)),
        peer_titles=list(dict.fromkeys(explicit_peers + taxonomy_peers)),
        recruiter_titles=list(dict.fromkeys(explicit_recruiters + [
            "Recruiter", "Talent Acquisition Partner", "Talent Partner",
        ])),
        apollo_departments=apollo_departments,
        occupation_keys=occupation_keys,
    )


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
