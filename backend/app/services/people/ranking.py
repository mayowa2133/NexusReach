"""Candidate and person ranking, scoring, and sort keys for people discovery."""

import logging
import re
from datetime import datetime, timezone


from app.models.job import Job
from app.models.person import Person
from app.utils.job_context import (
    JobContext,
)
from app.utils.relevance_scorer import score_candidate_relevance

from app.services.people.classify import _compute_match_metadata
from app.services.people.identity import _contains_any_keyword, _keyword_in_text, _normalize_identity
from app.services.people.titles import CONTROLLED_LEAD_KEYWORDS, MANAGER_TITLE_KEYWORDS, SENIORITY_ORDER, TALENT_TITLE_KEYWORDS, _candidate_seniority_level, _is_adjacent_recruiter_like, _is_manager_like, _is_recruiter_like, _is_senior_ic_fallback, _role_like_title, _is_founder_exec_title
from app.services.people.company_match import CURRENT_TRUSTED_SOURCES, _classify_employment_status, _trusted_public_match
from app.services.people.affinity import affinity_rank
from app.services.people.github_team_rank import github_team_rank
from app.services.people.context import _location_match_rank
from app.services.people.outcome_priors import outcome_prior_rank
logger = logging.getLogger(__name__)


def _hiring_team_rank(data: dict) -> int:
    """Literal req owner from LinkedIn's hiring-team panel — the top signal."""
    return 0 if data.get("_hiring_team_capture") else 1


SOURCE_PRIORITY = {
    "apollo": 0,
    "proxycurl": 1,
    "brave_hiring_team": 1,
    "serper_hiring_team": 1,
    # SearXNG is the default primary provider — rank its results alongside the
    # equivalent paid-provider families, not at the fallback floor (audit C1).
    "searxng_hiring_team": 1,
    "theorg_traversal": 2,
    "brave_search": 3,
    "serper_search": 3,
    "searxng_search": 3,
    "google_cse": 3,
    "brave_public_web": 4,
    "serper_public_web": 4,
    "tavily_public_web": 4,
    "searxng_public_web": 4,
    "github": 4,
}


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
            _hiring_team_rank(data),
            0 if data.get("_posting_contact") else 1,
            0 if data.get("_posted_this_req") else 1,
            0 if data.get("_actively_hiring") else 1,
            recruiter_scope_rank,
            location_rank,
            context_rank,
            explicit_role_rank,
            org_rank,
            source_rank,
            seniority_rank,
            weak_title_rank,
            github_team_rank(data),
            affinity_rank(data),
            outcome_prior_rank(data),
            role_title_rank,
            normalized_name,
        )
    if bucket == "hiring_managers":
        manager_keywords = MANAGER_TITLE_KEYWORDS + CONTROLLED_LEAD_KEYWORDS
        explicit_role_rank = 0 if _contains_any_keyword(title, manager_keywords) else 1 if _contains_any_keyword(snippet, manager_keywords) else 2
        # At startups the verified founder/C-level IS the hiring manager and
        # the decision maker, so verification tier and founder status outrank
        # title-seed alignment. Big-company searches keep title fit on top -
        # there, hundreds of employees are "verified" and the title is the
        # only thing that picks the right person.
        startup_priority: tuple = ()
        if context is not None and getattr(context, "startup", False):
            confidence = str(profile_data.get("company_match_confidence") or "")
            startup_priority = (
                _confidence_rank(confidence),
                0 if _is_founder_exec_title(title) else 1,
            )
        return (
            *startup_priority,
            _hiring_team_rank(data),
            github_team_rank(data),
            0 if data.get("_actively_hiring") else 1,
            _team_keyword_match_rank(data, bucket=bucket, context=context),
            location_rank,
            context_rank,
            org_rank,
            source_rank,
            seniority_rank,
            explicit_role_rank,
            weak_title_rank,
            affinity_rank(data),
            outcome_prior_rank(data),
            role_title_rank,
            normalized_name,
        )
    return (
        github_team_rank(data),
        org_rank,
        0 if data.get("_actively_hiring") else 1,
        _peer_title_alignment_rank(data, context=context),
        location_rank,
        context_rank,
        source_rank,
        seniority_rank,
        _recency_rank(data) if bucket == "peers" else 0,
        weak_title_rank,
        affinity_rank(data),
        outcome_prior_rank(data),
        role_title_rank,
        normalized_name,
    )


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


def _linkedin_signal_rank(person: Person) -> int:
    if bool(getattr(person, "followed_person", False)):
        return 0
    if bool(getattr(person, "followed_company", False)):
        return 1
    return 2


def _person_location_match_rank(
    person: Person, location_terms: list[str] | None = None
) -> int:
    """Rank 0 when a person's location matches one of the job's target locations.

    Target locations come from the job/company context (audit H1). Previously
    this hardcoded Toronto/Ontario, which only ever helped users searching in one
    region. With no target locations, location is neutral (rank 1 for everyone)
    so it never silently reorders toward a fixed city.
    """
    if not location_terms:
        return 1
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
    for term in location_terms:
        token = str(term or "").strip().lower()
        if len(token) >= 3 and token in location_text:
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
