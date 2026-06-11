"""Job-context geo signals and roles-context construction for people discovery."""

import logging
import re


from app.utils.job_context import (
    JobContext,
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
