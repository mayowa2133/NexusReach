"""People discovery service for company and job-aware search."""

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import apollo_client, brave_search_client, github_client, proxycurl_client
from app.models.company import Company
from app.models.job import Job
from app.models.person import Person
from app.services.employment_verification_service import verify_people_current_company
from app.utils.company_identity import (
    canonical_company_display_name,
    is_ambiguous_company_name,
    normalize_company_name,
    should_trust_company_enrichment,
)
from app.utils.job_context import JobContext, extract_job_context
from app.utils.relevance_scorer import score_candidate_relevance

RECRUITER_TITLE_KEYWORDS = (
    "recruiter",
    "talent acquisition",
    "talent partner",
    "sourcer",
    "hiring coordinator",
    "people partner",
    "people operations",
    "human resources",
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
}
SOURCE_PRIORITY = {
    "apollo": 0,
    "proxycurl": 1,
    "brave_hiring_team": 1,
    "brave_search": 2,
    "brave_public_web": 3,
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


def _normalize_identity(value: str | None) -> str:
    return " ".join((value or "").lower().split())


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


def _public_url_matches_company(public_url: str, company_name: str) -> bool:
    if not public_url:
        return False
    if is_ambiguous_company_name(company_name):
        return False
    return _slugify(company_name) in urlparse(public_url).path.lower()


def _candidate_matches_company(data: dict, company_name: str) -> bool:
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
        or _public_url_matches_company(public_url, company_name)
    )

    if host in CURRENT_TRUSTED_PUBLIC_HOSTS and not _public_url_matches_company(public_url, company_name):
        return False

    if title and not _role_like_title(title) and not _mentions_company(title, company_name):
        return False

    return company_mentioned


def _classify_employment_status(data: dict, company_name: str) -> str:
    source = data.get("source", "")
    title = data.get("title", "") or ""
    snippet = data.get("snippet", "") or ""
    public_url = _public_profile_url(data)
    host = _public_profile_host(data)
    haystack = " ".join(part for part in [title, snippet] if part).lower()

    if _mentions_company(haystack, company_name) and any(
        re.search(pattern, haystack) for pattern in FORMER_COMPANY_PATTERNS
    ):
        return "former"

    if source in CURRENT_TRUSTED_SOURCES:
        return "current"

    if host in CURRENT_TRUSTED_PUBLIC_HOSTS and _public_url_matches_company(public_url, company_name):
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
    return (
        _org_rank(bucket, data.get("_org_level", "ic")),
        _source_rank(data.get("source")),
        _context_rank(data, context),
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
        if bucket == "peers" and data.get("source") == "brave_public_web":
            continue
        if not _candidate_matches_company(data, company_name):
            continue

        person_type = _classify_person(
            data.get("title", ""),
            source=data.get("source", ""),
            snippet=data.get("snippet", ""),
        )
        if person_type != expected_type:
            continue

        employment_status = _classify_employment_status(data, company_name)
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


def _classify_person(title: str, source: str = "", snippet: str = "") -> str:
    """Classify a result into recruiter, hiring_manager, or peer."""
    haystack = " ".join(part for part in [title, snippet, source] if part).lower()
    if any(keyword in haystack for keyword in RECRUITER_TITLE_KEYWORDS):
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


async def _search_candidates(
    company_name: str,
    *,
    titles: list[str],
    departments: list[str] | None = None,
    seniority: list[str] | None = None,
    team_keywords: list[str] | None = None,
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
    if len(merged) < min_results:
        public_results = await brave_search_client.search_public_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            limit=max(limit, 5),
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
    if company:
        if len(requested_name) < len(company.name or ""):
            company.name = requested_name
        if not company.domain_trusted and is_ambiguous_company_name(requested_name):
            company.domain = None
            company.domain_trusted = False
            company.email_pattern = None
            company.email_pattern_confidence = None
        return company

    company_data = await apollo_client.search_company(requested_name)
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

    company = Company(
        user_id=user_id,
        name=requested_name,
        normalized_name=normalized_name,
        domain=trusted_domain,
        domain_trusted=bool(trusted_domain),
        size=str(company_data.get("size", "")) if company_data and use_apollo_enrichment else None,
        industry=company_data.get("industry") if company_data and use_apollo_enrichment else None,
        description=company_data.get("description") if company_data and use_apollo_enrichment else None,
        careers_url=company_data.get("careers_url") if company_data and use_apollo_enrichment else None,
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
            if data.get("profile_data"):
                profile_data = existing.profile_data if isinstance(existing.profile_data, dict) else {}
                profile_data.update(data.get("profile_data"))
                existing.profile_data = profile_data
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
        profile_data=data.get("profile_data") or {k: v for k, v in data.items() if k != "source"},
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

    recruiter_titles = [
        "technical recruiter",
        "engineering recruiter",
        "talent acquisition",
        "technical sourcer",
    ]
    manager_titles = roles or ["engineering manager", "technical lead", "team lead"]
    peer_titles = roles or ["software engineer", "backend engineer", "developer"]

    recruiter_results = _prepare_candidates(
        await _search_candidates(company_name, titles=recruiter_titles, limit=10),
        company_name=company_name,
        bucket="recruiters",
        context=None,
        limit=5,
    )
    manager_results = _prepare_candidates(
        await _search_candidates(
        company_name,
        titles=manager_titles,
        seniority=["manager", "director", "vp"],
        limit=10,
    ),
        company_name=company_name,
        bucket="hiring_managers",
        context=None,
        limit=5,
    )
    peer_results = _prepare_candidates(
        await _search_candidates(company_name, titles=peer_titles, limit=10),
        company_name=company_name,
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
    company = await get_or_create_company(db, user_id, job.company_name)
    min_results = 2

    recruiter_results = await _search_candidates(
        job.company_name,
        titles=context.recruiter_titles,
        departments=context.apollo_departments,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=10,
        min_results=min_results,
    )
    manager_results = await _search_candidates(
        job.company_name,
        titles=context.manager_titles,
        departments=context.apollo_departments,
        seniority=_manager_seniority_filters(context),
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=10,
        min_results=min_results,
    )
    peer_results = await _search_candidates(
        job.company_name,
        titles=context.peer_titles,
        departments=context.apollo_departments,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=10,
        min_results=min_results,
    )

    manager_results = await _score_contextual_candidates(
        manager_results,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
    )
    peer_results = await _score_contextual_candidates(
        peer_results,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
    )
    recruiter_results = _prepare_candidates(
        recruiter_results,
        company_name=job.company_name,
        bucket="recruiters",
        context=context,
        limit=5,
    )
    manager_results = _prepare_candidates(
        manager_results,
        company_name=job.company_name,
        bucket="hiring_managers",
        context=context,
        limit=5,
    )
    peer_results = _prepare_candidates(
        peer_results,
        company_name=job.company_name,
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
        if not _candidate_matches_company(data, job.company_name):
            continue
        if _classify_employment_status(data, job.company_name) == "former":
            continue
        data["_employment_status"] = _classify_employment_status(data, job.company_name)
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
