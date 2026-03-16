"""People Finder service — orchestrates Apollo, Proxycurl, and GitHub
to find relevant people at a target company."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import apollo_client, proxycurl_client, github_client
from app.models.company import Company
from app.models.job import Job
from app.models.person import Person
from app.utils.job_context import extract_job_context

# Title patterns for categorizing people
RECRUITER_TITLES = {"recruiter", "talent", "hiring", "people operations", "hr ", "human resources"}
MANAGER_TITLES = {"manager", "lead", "director", "head of", "vp ", "principal", "staff"}


def _classify_person(title: str) -> str:
    """Classify a person as recruiter, hiring_manager, or peer based on title."""
    title_lower = (title or "").lower()
    for keyword in RECRUITER_TITLES:
        if keyword in title_lower:
            return "recruiter"
    for keyword in MANAGER_TITLES:
        if keyword in title_lower:
            return "hiring_manager"
    return "peer"


async def get_or_create_company(
    db: AsyncSession, user_id: uuid.UUID, company_name: str
) -> Company:
    """Find existing company or create + enrich a new one."""
    result = await db.execute(
        select(Company).where(
            Company.user_id == user_id,
            Company.name.ilike(company_name),
        )
    )
    company = result.scalar_one_or_none()

    if company:
        return company

    # Try to enrich via Apollo
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
    """Create a Person record from API data, deduplicating by linkedin_url or apollo_id."""
    linkedin = data.get("linkedin_url", "")
    apollo_id = data.get("apollo_id", "")

    # Check if person already exists for this user (by linkedin_url or apollo_id)
    if linkedin:
        result = await db.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.linkedin_url == linkedin,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            # Backfill apollo_id if we didn't have it before
            if apollo_id and not existing.apollo_id:
                existing.apollo_id = apollo_id
            return existing

    if not linkedin and apollo_id:
        result = await db.execute(
            select(Person).where(
                Person.user_id == user_id,
                Person.apollo_id == apollo_id,
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
    )
    db.add(person)
    return person


async def search_people_at_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
    roles: list[str] | None = None,
    github_org: str | None = None,
) -> dict:
    """Find people at a company, categorized by type.

    Returns:
        {
            "company": Company,
            "recruiters": [Person, ...],
            "hiring_managers": [Person, ...],
            "peers": [Person, ...],
        }
    """
    company = await get_or_create_company(db, user_id, company_name)

    # Gather people from Apollo (primary source)
    recruiter_results = await apollo_client.search_people(
        company_name,
        titles=["recruiter", "talent acquisition", "technical recruiter"],
        limit=3,
    )
    manager_results = await apollo_client.search_people(
        company_name,
        titles=roles or ["engineering manager", "team lead", "hiring manager"],
        seniority=["manager", "director", "vp"],
        limit=3,
    )
    peer_results = await apollo_client.search_people(
        company_name,
        titles=roles or ["software engineer", "developer", "swe"],
        limit=3,
    )

    # GitHub org members (if org name provided)
    github_members: list[dict] = []
    if github_org:
        github_members = await github_client.search_org_members(github_org, limit=5)
        # Enrich with repos
        for member in github_members:
            repos = await github_client.get_user_repos(member["login"], limit=3)
            languages = list({r["language"] for r in repos if r.get("language")})
            member["github_data"] = {"repos": repos, "languages": languages}
            member["github_url"] = member.get("github_url", "")

    # Store and categorize
    recruiters: list[Person] = []
    hiring_managers: list[Person] = []
    peers: list[Person] = []

    for data in recruiter_results:
        person = await _store_person(db, user_id, company.id, data, "recruiter")
        recruiters.append(person)

    for data in manager_results:
        ptype = _classify_person(data.get("title", ""))
        person = await _store_person(db, user_id, company.id, data, ptype)
        if ptype == "recruiter":
            recruiters.append(person)
        else:
            hiring_managers.append(person)

    for data in peer_results:
        person = await _store_person(db, user_id, company.id, data, "peer")
        peers.append(person)

    for data in github_members:
        person = await _store_person(db, user_id, company.id, data, "peer")
        peers.append(person)

    await db.commit()

    return {
        "company": company,
        "recruiters": recruiters,
        "hiring_managers": hiring_managers,
        "peers": peers,
    }


async def search_people_for_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict:
    """Find people at a company using job context for targeted search.

    Extracts department, team, and seniority from the job posting, then
    runs targeted Apollo searches for recruiters, managers, and peers
    on the same team.

    Returns:
        {
            "company": Company,
            "recruiters": [Person, ...],
            "hiring_managers": [Person, ...],
            "peers": [Person, ...],
            "job_context": JobContext,
        }
    """
    # Load the job (scoped to user)
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    # Extract context from job title + description
    context = extract_job_context(job.title, job.description)

    company = await get_or_create_company(db, user_id, job.company_name)

    # --- Targeted searches using extracted context ---
    min_results = 2  # fallback threshold

    # Recruiters
    recruiter_results = await apollo_client.search_people(
        job.company_name,
        titles=context.recruiter_titles,
        departments=context.apollo_departments,
        limit=3,
    )
    if len(recruiter_results) < min_results:
        recruiter_results = await apollo_client.search_people(
            job.company_name,
            titles=context.recruiter_titles,
            limit=3,
        )

    # Managers
    manager_results = await apollo_client.search_people(
        job.company_name,
        titles=context.manager_titles,
        seniority=["manager", "director", "vp"],
        departments=context.apollo_departments,
        limit=3,
    )
    if len(manager_results) < min_results:
        manager_results = await apollo_client.search_people(
            job.company_name,
            titles=context.manager_titles,
            seniority=["manager", "director", "vp"],
            limit=3,
        )

    # Peers
    peer_results = await apollo_client.search_people(
        job.company_name,
        titles=context.peer_titles,
        departments=context.apollo_departments,
        limit=3,
    )
    if len(peer_results) < min_results:
        peer_results = await apollo_client.search_people(
            job.company_name,
            titles=context.peer_titles,
            limit=3,
        )

    # Store and categorize (reuse existing helpers)
    recruiters: list[Person] = []
    hiring_managers: list[Person] = []
    peers: list[Person] = []

    for data in recruiter_results:
        person = await _store_person(db, user_id, company.id, data, "recruiter")
        recruiters.append(person)

    for data in manager_results:
        ptype = _classify_person(data.get("title", ""))
        person = await _store_person(db, user_id, company.id, data, ptype)
        if ptype == "recruiter":
            recruiters.append(person)
        else:
            hiring_managers.append(person)

    for data in peer_results:
        person = await _store_person(db, user_id, company.id, data, "peer")
        peers.append(person)

    await db.commit()

    return {
        "company": company,
        "recruiters": recruiters,
        "hiring_managers": hiring_managers,
        "peers": peers,
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
    """Enrich a single person from their LinkedIn URL via Proxycurl."""
    # Check if already exists
    result = await db.execute(
        select(Person).where(
            Person.user_id == user_id,
            Person.linkedin_url == linkedin_url,
        )
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
