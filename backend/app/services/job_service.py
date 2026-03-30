"""Job intelligence service — aggregates, deduplicates, scores, and tracks jobs."""

import hashlib
import logging
import uuid
from urllib.parse import urlparse

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import jsearch_client, adzuna_client, ats_client, remote_jobs_client, newgrad_jobs_client
from app.models.job import Job
from app.models.profile import Profile
from app.models.search_preference import SearchPreference

logger = logging.getLogger(__name__)


# --- Deduplication ---

def _fingerprint(company_name: str | None, title: str | None, location: str | None) -> str:
    """Create a fingerprint for deduplication based on company + title + location."""
    raw = (
        f"{(company_name or '').lower().strip()}|"
        f"{(title or '').lower().strip()}|"
        f"{(location or '').lower().strip()}"
    )
    return hashlib.md5(raw.encode()).hexdigest()


def _canonical_job_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = ats_client.parse_ats_job_url(url)
    if parsed and parsed.canonical_url:
        return parsed.canonical_url.rstrip("/")
    normalized = url.rstrip("/")
    if not normalized:
        return None
    parsed_url = urlparse(normalized)
    if parsed_url.scheme and parsed_url.netloc:
        return normalized
    return None


def _result_first(result) -> Job | None:
    scalars = getattr(result, "scalars", None)
    if callable(scalars):
        return scalars().first()
    return result.scalar_one_or_none()


def _refresh_existing_exact_job(
    job: Job,
    data: dict,
    *,
    fingerprint: str,
    score: float,
    breakdown: dict,
) -> None:
    job.external_id = data.get("external_id") or job.external_id
    job.title = data.get("title") or job.title
    job.company_name = data.get("company_name") or job.company_name
    job.location = data.get("location")
    job.remote = data.get("remote", job.remote)
    job.url = data.get("url") or job.url
    job.description = data.get("description")
    job.source = data.get("source", job.source)
    job.ats = data.get("ats", job.ats)
    job.ats_slug = data.get("ats_slug", job.ats_slug)
    job.posted_at = data.get("posted_at")
    job.match_score = score
    job.score_breakdown = breakdown
    job.fingerprint = fingerprint
    job.department = data.get("department")
    job.employment_type = data.get("employment_type")


async def _find_existing_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    ats: str | None,
    external_id: str | None,
    url: str | None,
    fingerprint: str | None,
) -> Job | None:
    if ats and external_id:
        result = await db.execute(
            select(Job)
            .where(Job.user_id == user_id, Job.ats == ats, Job.external_id == external_id)
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        existing = _result_first(result)
        if existing:
            return existing

    normalized_url = _canonical_job_url(url)
    if ats and normalized_url:
        result = await db.execute(
            select(Job)
            .where(Job.user_id == user_id, Job.ats == ats, Job.url.is_not(None))
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        for existing in result.scalars().all():
            if _canonical_job_url(existing.url) == normalized_url:
                return existing

    if fingerprint:
        result = await db.execute(
            select(Job)
            .where(Job.user_id == user_id, Job.fingerprint == fingerprint)
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        existing = _result_first(result)
        if existing:
            return existing

    return None


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
                 Options: jsearch, adzuna, remotive, jobicy, dice, simplify, newgrad
    """
    all_sources = sources or ["jsearch", "adzuna", "remotive", "dice", "newgrad"]

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
    if "newgrad" in all_sources:
        raw_jobs.extend(await newgrad_jobs_client.search_newgrad_jobs(
            query=query, limit=limit,
        ))

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
        existing = await _find_existing_job(
            db,
            user_id=user_id,
            ats=data.get("ats"),
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )
        if existing:
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
    company_slug: str | None,
    ats_type: str | None,
    limit: int | None = None,
    job_url: str | None = None,
) -> list[Job]:
    """Search a supported board-backed ATS or ingest a single exact job URL."""
    target_external_id: str | None = None
    target_url: str | None = None
    parsed_job_url: ats_client.ParsedATSJobURL | None = None

    if job_url:
        parsed_job_url = ats_client.parse_ats_job_url(job_url)
        if not parsed_job_url:
            raise ValueError("Unsupported or invalid job posting URL.")
        company_slug = parsed_job_url.company_slug
        ats_type = parsed_job_url.ats_type
        target_external_id = parsed_job_url.external_id
        target_url = parsed_job_url.canonical_url

    if not ats_type:
        raise ValueError("ATS search requires either job_url or company_slug plus ats_type.")

    adapter = ats_client.get_adapter(ats_type)
    if not adapter:
        raise ValueError("Unsupported or invalid job posting URL.")

    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if job_url and parsed_job_url and adapter.fetch_exact is not None:
        try:
            raw_jobs = await ats_client.fetch_exact_job(parsed_job_url)
        except ats_client.ExactJobFetchError as exc:
            raise ValueError(str(exc)) from exc
        exact_job_lookup = True
    else:
        exact_job_lookup = False
        if not company_slug or adapter.search_board is None:
            raise ValueError("This job platform currently requires a direct job posting URL.")
        raw_jobs = await adapter.search_board(company_slug, limit)

    stored_jobs: list[Job] = []
    board_jobs: list[Job] = []
    seen_job_keys: set[str] = set()
    for data in raw_jobs:
        fp = _fingerprint(data.get("company_name", ""), data["title"], data.get("location", ""))
        job_key = (
            f"external:{data.get('external_id')}"
            if data.get("external_id")
            else f"url:{_canonical_job_url(data.get('url'))}"
            if _canonical_job_url(data.get("url"))
            else f"fingerprint:{fp}"
        )
        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)

        job_ats = data.get("ats", ats_type)
        job_ats_slug = data.get("ats_slug", company_slug)
        score, breakdown = _score_job(data, profile)
        existing_job = await _find_existing_job(
            db,
            user_id=user_id,
            ats=job_ats,
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )
        if existing_job:
            if exact_job_lookup:
                _refresh_existing_exact_job(
                    existing_job,
                    data,
                    fingerprint=fp,
                    score=score,
                    breakdown=breakdown,
                )
            board_jobs.append(existing_job)
            continue

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
            ats=job_ats,
            ats_slug=job_ats_slug,
            posted_at=data.get("posted_at"),
            match_score=score,
            score_breakdown=breakdown,
            fingerprint=fp,
            department=data.get("department"),
            employment_type=data.get("employment_type"),
        )
        db.add(job)
        stored_jobs.append(job)
        board_jobs.append(job)

    await db.commit()

    if not job_url:
        return stored_jobs

    normalized_target = _canonical_job_url(target_url or job_url)
    exact_matches = [
        job
        for job in board_jobs
        if (target_external_id and job.external_id == target_external_id)
        or (_canonical_job_url(job.url) and _canonical_job_url(job.url) == normalized_target)
    ]
    if not exact_matches:
        return board_jobs

    exact_ids = {job.id for job in exact_matches}
    ordered_jobs = exact_matches + [job for job in board_jobs if job.id not in exact_ids]
    return ordered_jobs


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
    *,
    employment_type: str | None = None,
    salary_min: float | None = None,
    remote: bool | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Job], int]:
    """Get saved jobs for a user with optional filtering and pagination.

    Returns ``(jobs, total_count)``.
    """
    from app.utils.pagination import paginate

    query = select(Job).where(Job.user_id == user_id)
    if stage:
        query = query.where(Job.stage == stage)
    if starred is not None:
        query = query.where(Job.starred == starred)
    if employment_type:
        query = query.where(Job.employment_type == employment_type)
    if salary_min is not None:
        query = query.where(Job.salary_max >= salary_min)
    if remote is not None:
        query = query.where(Job.remote == remote)
    if search:
        term = f"%{search}%"
        query = query.where(
            Job.title.ilike(term) | Job.company_name.ilike(term)
        )

    if sort_by == "score":
        query = query.order_by(Job.match_score.desc().nullslast())
    elif sort_by == "date":
        query = query.order_by(Job.created_at.desc())
    else:
        query = query.order_by(Job.created_at.desc())

    return await paginate(db, query, limit=limit, offset=offset)


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


# --- Default Seed Feeds ---

DEFAULT_SEED_SEARCHES = [
    {"query": "Software Engineer", "location": None, "remote_only": False},
    {"query": "New Grad Software", "location": None, "remote_only": False},
]


async def seed_default_feeds(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    """Seed default job searches for a brand-new user.

    Idempotent: does nothing if the user already has any jobs or search
    preferences.  Returns the total number of new jobs stored.
    """
    job_count_r = await db.execute(
        select(sa_func.count()).select_from(Job).where(Job.user_id == user_id)
    )
    if (job_count_r.scalar() or 0) > 0:
        return 0

    pref_count_r = await db.execute(
        select(sa_func.count())
        .select_from(SearchPreference)
        .where(SearchPreference.user_id == user_id)
    )
    if (pref_count_r.scalar() or 0) > 0:
        return 0

    total_new = 0
    for seed in DEFAULT_SEED_SEARCHES:
        try:
            stored = await search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
            )
            total_new += len(stored)
        except Exception:
            logger.exception("Failed to seed default feed: %s", seed["query"])

    logger.info("Seeded %d default jobs for user %s", total_new, user_id)
    return total_new


# Broader discovery queries spanning multiple roles and industries
DISCOVER_QUERIES = [
    {"query": "Software Engineer", "location": None, "remote_only": False},
    {"query": "Frontend Developer", "location": None, "remote_only": False},
    {"query": "Backend Developer", "location": None, "remote_only": False},
    {"query": "Full Stack Developer", "location": None, "remote_only": False},
    {"query": "Data Scientist", "location": None, "remote_only": False},
    {"query": "Product Manager", "location": None, "remote_only": False},
    {"query": "New Grad Software", "location": None, "remote_only": False},
]


async def discover_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str] | None = None,
) -> int:
    """Run a batch of job searches across free sources.

    Unlike seed_default_feeds this always runs — it is the manual
    "Discover Jobs" action.  Deduplication is handled by search_jobs,
    so repeat runs are safe and will only store genuinely new results.

    Args:
        queries: Optional custom list of search terms.  Falls back to
                 DISCOVER_QUERIES when not supplied.
    """
    search_list = (
        [{"query": q, "location": None, "remote_only": False} for q in queries]
        if queries
        else DISCOVER_QUERIES
    )

    total_new = 0
    for seed in search_list:
        try:
            stored = await search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
            )
            total_new += len(stored)
        except Exception:
            logger.exception("Discover failed for query: %s", seed["query"])

    logger.info("Discovered %d new jobs for user %s", total_new, user_id)
    return total_new
