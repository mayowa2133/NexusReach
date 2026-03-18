"""People discovery service for company and job-aware search."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import apollo_client, brave_search_client, github_client, proxycurl_client
from app.models.company import Company
from app.models.job import Job
from app.models.person import Person
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


def _normalize_identity(value: str | None) -> str:
    return " ".join((value or "").lower().split())


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

    return _dedupe_candidates(apollo_filtered, apollo_unfiltered, brave_results, public_results)[:limit]


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
    result = await db.execute(
        select(Company).where(
            Company.user_id == user_id,
            Company.name.ilike(company_name),
        )
    )
    company = result.scalar_one_or_none()
    if company:
        return company

    company_data = await apollo_client.search_company(company_name)
    company = Company(
        user_id=user_id,
        name=company_data.get("name", company_name) if company_data else company_name,
        domain=company_data.get("domain") if company_data else None,
        size=str(company_data.get("size", "")) if company_data else None,
        industry=company_data.get("industry") if company_data else None,
        description=company_data.get("description") if company_data else None,
        careers_url=company_data.get("careers_url") if company_data else None,
        enriched_at=datetime.now(timezone.utc) if company_data else None,
    )
    db.add(company)
    await db.flush()
    return company


async def _store_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_id: uuid.UUID | None,
    data: dict,
    person_type: str,
) -> Person:
    """Create or update a Person record from API data."""
    linkedin = data.get("linkedin_url", "")
    apollo_id = data.get("apollo_id", "")

    if linkedin:
        result = await db.execute(
            select(Person).where(Person.user_id == user_id, Person.linkedin_url == linkedin)
        )
        existing = result.scalar_one_or_none()
        if existing:
            if apollo_id and not existing.apollo_id:
                existing.apollo_id = apollo_id
            if not existing.title and data.get("title"):
                existing.title = data.get("title")
            if not existing.full_name and data.get("full_name"):
                existing.full_name = data.get("full_name")
            if data.get("profile_data"):
                existing.profile_data = data.get("profile_data")
            return existing

    if not linkedin and apollo_id:
        result = await db.execute(
            select(Person).where(Person.user_id == user_id, Person.apollo_id == apollo_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
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
        existing = result.scalar_one_or_none()
        if existing:
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
    db.add(person)
    return person


def _apply_match_metadata(person: Person, data: dict, person_type: str, context: JobContext | None) -> None:
    match_quality, match_reason = _compute_match_metadata(data, person_type, context)
    setattr(person, "match_quality", match_quality)
    setattr(person, "match_reason", match_reason)


def _append_bucket(
    bucketed: dict[str, list[Person]],
    seen: dict[str, set[uuid.UUID]],
    person: Person,
    data: dict,
    explicit_type: str | None = None,
    context: JobContext | None = None,
) -> None:
    person_type = explicit_type or _classify_person(
        person.title or data.get("title", ""),
        source=data.get("source", ""),
        snippet=data.get("snippet", ""),
    )
    person.person_type = person_type
    _apply_match_metadata(person, data, person_type, context)

    bucket_name = {
        "recruiter": "recruiters",
        "hiring_manager": "hiring_managers",
        "peer": "peers",
    }[person_type]
    if person.id in seen[bucket_name]:
        return
    seen[bucket_name].add(person.id)
    bucketed[bucket_name].append(person)


async def search_people_at_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
    roles: list[str] | None = None,
    github_org: str | None = None,
) -> dict:
    """Find people at a company using company-level search."""
    company = await get_or_create_company(db, user_id, company_name)

    recruiter_titles = ["technical recruiter", "engineering recruiter", "talent acquisition"]
    manager_titles = roles or ["engineering manager", "director of engineering", "team lead"]
    peer_titles = roles or ["software engineer", "backend engineer", "developer"]

    recruiter_results = await _search_candidates(company_name, titles=recruiter_titles, limit=5)
    manager_results = await _search_candidates(
        company_name,
        titles=manager_titles,
        seniority=["manager", "director", "vp"],
        limit=5,
    )
    peer_results = await _search_candidates(company_name, titles=peer_titles, limit=5)

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
        person = await _store_person(db, user_id, company.id, data, "recruiter")
        _append_bucket(bucketed, seen, person, data, explicit_type="recruiter")

    for data in manager_results:
        person = await _store_person(db, user_id, company.id, data, _classify_person(data.get("title", "")))
        _append_bucket(bucketed, seen, person, data)

    for data in peer_results:
        person = await _store_person(db, user_id, company.id, data, "peer")
        _append_bucket(bucketed, seen, person, data)

    for data in github_members:
        person = await _store_person(db, user_id, company.id, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer")

    await db.commit()
    return {"company": company, **bucketed}


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
        limit=5,
        min_results=min_results,
    )
    manager_results = await _search_candidates(
        job.company_name,
        titles=context.manager_titles,
        departments=context.apollo_departments,
        seniority=["manager", "director", "vp"],
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=5,
        min_results=min_results,
    )
    peer_results = await _search_candidates(
        job.company_name,
        titles=context.peer_titles,
        departments=context.apollo_departments,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=5,
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

    hiring_team_results = await brave_search_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        limit=3,
    )

    bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
    seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}

    for data in recruiter_results:
        person = await _store_person(db, user_id, company.id, data, "recruiter")
        _append_bucket(bucketed, seen, person, data, explicit_type="recruiter", context=context)

    for data in manager_results:
        person = await _store_person(db, user_id, company.id, data, _classify_person(data.get("title", ""), data.get("source", ""), data.get("snippet", "")))
        _append_bucket(bucketed, seen, person, data, context=context)

    for data in peer_results:
        person = await _store_person(db, user_id, company.id, data, "peer")
        _append_bucket(bucketed, seen, person, data, context=context)

    for data in hiring_team_results:
        person = await _store_person(db, user_id, company.id, data, _classify_person(data.get("title", ""), data.get("source", ""), data.get("snippet", "")))
        _append_bucket(bucketed, seen, person, data, context=context)

    await db.commit()
    return {
        "company": company,
        **bucketed,
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
    query = select(Person).where(Person.user_id == user_id)
    if company_id:
        query = query.where(Person.company_id == company_id)
    query = query.order_by(Person.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())
