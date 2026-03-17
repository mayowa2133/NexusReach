"""Job intelligence service — aggregates, deduplicates, scores, and tracks jobs."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import jsearch_client, adzuna_client, ats_client, remote_jobs_client
from app.models.job import Job
from app.models.profile import Profile
from app.models.search_preference import SearchPreference


# --- Deduplication ---

def _fingerprint(company_name: str, title: str, location: str) -> str:
    """Create a fingerprint for deduplication based on company + title + location."""
    raw = f"{company_name.lower().strip()}|{title.lower().strip()}|{location.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


# --- Scoring ---

def _score_job(job_data: dict, profile: Profile | None) -> tuple[float, dict]:
    """Score a job against the user's profile.

    Returns:
        (score 0-100, breakdown dict)
    """
    if not profile:
        return 0.0, {}

    breakdown: dict[str, float] = {}
    title = (job_data.get("title") or "").lower()
    description = (job_data.get("description") or "").lower()
    company = (job_data.get("company_name") or "").lower()
    location = (job_data.get("location") or "").lower()
    combined = f"{title} {description}"

    # 1. Role match (0-30 points)
    role_score = 0.0
    if profile.target_roles:
        for role in profile.target_roles:
            if role.lower() in title:
                role_score = 30.0
                break
            elif role.lower() in description:
                role_score = 15.0
    breakdown["role_match"] = role_score

    # 2. Skills match (0-30 points)
    skills_score = 0.0
    if profile.resume_parsed and profile.resume_parsed.get("skills"):
        skills = profile.resume_parsed["skills"]
        matches = sum(1 for s in skills if s.lower() in combined)
        skills_score = min(30.0, (matches / max(len(skills), 1)) * 60.0)
    breakdown["skills_match"] = skills_score

    # 3. Industry match (0-15 points)
    industry_score = 0.0
    if profile.target_industries:
        for ind in profile.target_industries:
            if ind.lower() in combined or ind.lower() in company:
                industry_score = 15.0
                break
    breakdown["industry_match"] = industry_score

    # 4. Location match (0-15 points)
    location_score = 0.0
    if profile.target_locations:
        for loc in profile.target_locations:
            if loc.lower() in location:
                location_score = 15.0
                break
        if job_data.get("remote"):
            location_score = max(location_score, 10.0)
    elif job_data.get("remote"):
        location_score = 10.0
    breakdown["location_match"] = location_score

    # 5. Experience level signals (0-10 points)
    level_score = 5.0  # default mid
    level_keywords = {"new grad", "entry level", "junior", "associate", "intern"}
    senior_keywords = {"senior", "staff", "principal", "lead", "architect"}
    if any(kw in title for kw in level_keywords):
        level_score = 10.0  # great for new grads
    elif any(kw in title for kw in senior_keywords):
        level_score = 2.0  # likely too senior
    breakdown["level_fit"] = level_score

    total = sum(breakdown.values())
    return round(total, 1), breakdown


# --- Aggregation ---

async def search_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    location: str | None = None,
    remote_only: bool = False,
    sources: list[str] | None = None,
    limit: int = 20,
) -> list[Job]:
    """Search for jobs across all sources, deduplicate, score, and store.

    Args:
        sources: List of sources to search. None = all.
                 Options: jsearch, adzuna, remotive, jobicy, dice, simplify
    """
    all_sources = sources or ["jsearch", "adzuna", "remotive"]

    # Load user profile for scoring
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    # Gather jobs from all sources
    raw_jobs: list[dict] = []

    if "jsearch" in all_sources:
        raw_jobs.extend(await jsearch_client.search_jobs(
            query, location=location, remote_only=remote_only, limit=limit
        ))
    if "adzuna" in all_sources:
        raw_jobs.extend(await adzuna_client.search_jobs(
            query, location=location, limit=limit
        ))
    if "remotive" in all_sources:
        raw_jobs.extend(await remote_jobs_client.search_remotive(query, limit=limit))
    if "jobicy" in all_sources:
        raw_jobs.extend(await remote_jobs_client.search_jobicy(query, limit=limit))
    if "dice" in all_sources:
        raw_jobs.extend(await remote_jobs_client.search_dice(query, location=location, limit=limit))
    if "simplify" in all_sources:
        raw_jobs.extend(await remote_jobs_client.fetch_simplify_jobs(limit=limit))

    # Deduplicate and store
    stored_jobs: list[Job] = []
    seen_fingerprints: set[str] = set()

    for data in raw_jobs:
        fp = _fingerprint(
            data.get("company_name", ""),
            data.get("title", ""),
            data.get("location", ""),
        )

        if fp in seen_fingerprints:
            continue
        seen_fingerprints.add(fp)

        # Check if already stored for this user
        existing = await db.execute(
            select(Job).where(Job.user_id == user_id, Job.fingerprint == fp)
        )
        if existing.scalar_one_or_none():
            continue

        # Score
        score, breakdown = _score_job(data, profile)

        job = Job(
            user_id=user_id,
            external_id=data.get("external_id"),
            title=data["title"],
            company_name=data.get("company_name", "Unknown"),
            company_logo=data.get("company_logo"),
            location=data.get("location"),
            remote=data.get("remote", False),
            url=data.get("url"),
            description=data.get("description"),
            employment_type=data.get("employment_type"),
            salary_min=data.get("salary_min"),
            salary_max=data.get("salary_max"),
            salary_currency=data.get("salary_currency"),
            source=data.get("source", "unknown"),
            ats=data.get("ats"),
            ats_slug=data.get("ats_slug"),
            posted_at=data.get("posted_at"),
            match_score=score,
            score_breakdown=breakdown,
            fingerprint=fp,
            tags=data.get("tags"),
            department=data.get("department"),
        )
        db.add(job)
        stored_jobs.append(job)

    # Auto-save search preference for Celery auto-refresh
    pref_stmt = select(SearchPreference).where(
        SearchPreference.user_id == user_id,
        SearchPreference.query == query.strip(),
    )
    pref_result = await db.execute(pref_stmt)
    existing_pref = pref_result.scalar_one_or_none()
    if not existing_pref:
        db.add(SearchPreference(
            user_id=user_id,
            query=query.strip(),
            location=location,
            remote_only=remote_only,
        ))

    await db.commit()
    return stored_jobs


async def search_ats_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_slug: str,
    ats_type: str,
    limit: int = 20,
) -> list[Job]:
    """Search a specific ATS board for jobs."""
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if ats_type == "greenhouse":
        raw_jobs = await ats_client.search_greenhouse(company_slug, limit)
    elif ats_type == "lever":
        raw_jobs = await ats_client.search_lever(company_slug, limit)
    elif ats_type == "ashby":
        raw_jobs = await ats_client.search_ashby(company_slug, limit)
    else:
        return []

    stored_jobs: list[Job] = []
    for data in raw_jobs:
        fp = _fingerprint(data.get("company_name", ""), data["title"], data.get("location", ""))

        existing = await db.execute(
            select(Job).where(Job.user_id == user_id, Job.fingerprint == fp)
        )
        if existing.scalar_one_or_none():
            continue

        score, breakdown = _score_job(data, profile)

        job = Job(
            user_id=user_id,
            external_id=data.get("external_id"),
            title=data["title"],
            company_name=data.get("company_name", company_slug),
            location=data.get("location"),
            remote=data.get("remote", False),
            url=data.get("url"),
            description=data.get("description"),
            source=data.get("source", ats_type),
            ats=ats_type,
            ats_slug=company_slug,
            posted_at=data.get("posted_at"),
            match_score=score,
            score_breakdown=breakdown,
            fingerprint=fp,
            department=data.get("department"),
        )
        db.add(job)
        stored_jobs.append(job)

    await db.commit()
    return stored_jobs


async def toggle_job_starred(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    starred: bool,
) -> Job:
    """Toggle a job's starred status."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.starred = starred
    await db.commit()
    await db.refresh(job)
    return job


async def get_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    stage: str | None = None,
    sort_by: str = "score",
    starred: bool | None = None,
) -> list[Job]:
    """Get all saved jobs for a user, optionally filtered by stage and starred."""
    query = select(Job).where(Job.user_id == user_id)
    if stage:
        query = query.where(Job.stage == stage)
    if starred is not None:
        query = query.where(Job.starred == starred)

    if sort_by == "score":
        query = query.order_by(Job.match_score.desc().nullslast())
    elif sort_by == "date":
        query = query.order_by(Job.created_at.desc())
    else:
        query = query.order_by(Job.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


async def update_job_stage(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    stage: str,
    notes: str | None = None,
) -> Job:
    """Update a job's kanban stage."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.stage = stage
    if notes is not None:
        job.notes = notes
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job | None:
    """Get a single job by ID."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    return result.scalar_one_or_none()
