"""Job intelligence service — aggregates, deduplicates, scores, and tracks jobs."""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from sqlalchemy import String, func as sa_func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import (
    adzuna_client,
    amazon_client,
    apple_client,
    ats_client,
    conviction_jobs_client,
    curated_startups_client,
    google_client,
    jsearch_client,
    lever_scrape_client,
    meta_client,
    microsoft_client,
    newgrad_jobs_client,
    public_page_client,
    remote_jobs_client,
    speedrun_jobs_client,
    tesla_client,
    ventureloop_jobs_client,
    wellfound_jobs_client,
    workday_client,
    yc_jobs_client,
)
from app.models.company import Company
from app.models.job import Job
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.profile import Profile
from app.models.resume_artifact import ResumeArtifact
from app.models.search_preference import SearchPreference
from app.models.tailored_resume import TailoredResume
from app.services.job_research_snapshot_service import (
    get_job_research_snapshot,
    serialize_snapshot,
)
from app.utils.experience_level import (
    classify_experience_level_for_job,
)
from app.utils.company_identity import normalize_company_name
from app.utils.startup_jobs import (
    STARTUP_TAG,
    append_startup_tags,
    extract_candidate_links,
    has_startup_tag,
    is_supported_job_link,
    job_matches_any_query,
    looks_like_careers_page,
    merge_startup_tags,
    merge_tags,
    startup_discover_queries,
    startup_source_tag,
    startup_tags,
)

logger = logging.getLogger(__name__)

STARTUP_BOARD_SOURCES = ["yc_jobs", "wellfound", "ventureloop"]
STARTUP_LINK_RESOLVE_CONCURRENCY = 6
STARTUP_MAX_RESOLVED_LINKS_PER_COMPANY = 3


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
        return urlunparse(parsed_url._replace(query="", fragment="")).rstrip("/")
    return None


def _result_first(result) -> Job | None:
    scalars = getattr(result, "scalars", None)
    if callable(scalars):
        return scalars().first()
    return result.scalar_one_or_none()


def _job_source_key(data: dict | None = None, *, source: str | None = None, ats: str | None = None) -> str | None:
    if source:
        return source
    if data is not None and data.get("source"):
        return data.get("source")
    if ats:
        return ats
    if data is not None:
        return data.get("ats")
    return None


def _job_identity_key(data: dict, *, fingerprint: str) -> str:
    source_key = _job_source_key(data)
    external_id = data.get("external_id")
    if source_key and external_id:
        return f"source:{source_key}:external:{external_id}"

    canonical_url = _canonical_job_url(data.get("url"))
    if source_key and canonical_url:
        return f"source:{source_key}:url:{canonical_url}"
    if canonical_url:
        return f"url:{canonical_url}"

    return f"fingerprint:{fingerprint}"


def _coerce_posted_at(value: str | None) -> str | None:
    """Normalize posted_at to None when empty or whitespace-only."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _experience_level_for_job(job_data: dict) -> str:
    return classify_experience_level_for_job(
        job_data.get("title", ""),
        source=job_data.get("source"),
        level_label=job_data.get("level_label"),
    )


def _apply_if_present(job: Job, attr: str, value) -> None:
    if isinstance(value, str):
        if value.strip():
            setattr(job, attr, value)
        return
    if value is not None:
        setattr(job, attr, value)


def _with_extra_tags(data: dict, extra_tags: list[str] | None) -> dict:
    if not extra_tags:
        return data
    return {
        **data,
        "tags": merge_tags(data.get("tags"), extra_tags),
    }


def _refresh_existing_job(
    job: Job,
    data: dict,
    *,
    fingerprint: str,
    score: float,
    breakdown: dict,
    experience_level: str,
) -> None:
    _apply_if_present(job, "external_id", data.get("external_id"))
    _apply_if_present(job, "title", data.get("title"))
    _apply_if_present(job, "company_name", data.get("company_name"))
    _apply_if_present(job, "company_logo", data.get("company_logo"))
    _apply_if_present(job, "location", data.get("location"))
    if data.get("remote") is not None:
        job.remote = bool(data.get("remote"))
    _apply_if_present(job, "url", data.get("url"))
    _apply_if_present(job, "apply_url", data.get("apply_url"))
    _apply_if_present(job, "description", data.get("description"))
    _apply_if_present(job, "source", data.get("source"))
    _apply_if_present(job, "ats", data.get("ats"))
    _apply_if_present(job, "ats_slug", data.get("ats_slug"))
    _apply_if_present(job, "posted_at", data.get("posted_at"))
    job.match_score = score
    job.score_breakdown = breakdown
    job.fingerprint = fingerprint
    _apply_if_present(job, "department", data.get("department"))
    _apply_if_present(job, "employment_type", data.get("employment_type"))
    if data.get("salary_min") is not None:
        job.salary_min = data.get("salary_min")
    if data.get("salary_max") is not None:
        job.salary_max = data.get("salary_max")
    _apply_if_present(job, "salary_currency", data.get("salary_currency"))
    if data.get("tags") is not None:
        job.tags = merge_startup_tags(job.tags, data.get("tags"))
    job.experience_level = experience_level


def _build_job(
    *,
    user_id: uuid.UUID,
    data: dict,
    score: float,
    breakdown: dict,
    fingerprint: str,
) -> Job:
    return Job(
        user_id=user_id,
        external_id=data.get("external_id"),
        title=data.get("title", ""),
        company_name=data.get("company_name", "Unknown"),
        company_logo=data.get("company_logo"),
        location=data.get("location"),
        remote=data.get("remote", False),
        url=data.get("url"),
        apply_url=data.get("apply_url"),
        description=data.get("description"),
        employment_type=data.get("employment_type"),
        experience_level=_experience_level_for_job(data),
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        salary_currency=data.get("salary_currency"),
        source=data.get("source", "unknown"),
        ats=data.get("ats"),
        ats_slug=data.get("ats_slug"),
        posted_at=_coerce_posted_at(data.get("posted_at")),
        match_score=score,
        score_breakdown=breakdown,
        fingerprint=fingerprint,
        tags=data.get("tags"),
        department=data.get("department"),
    )


async def _find_existing_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str | None,
    ats: str | None,
    external_id: str | None,
    url: str | None,
    fingerprint: str | None,
) -> Job | None:
    source_key = _job_source_key(source=source, ats=ats)

    if source_key and external_id:
        result = await db.execute(
            select(Job)
            .where(Job.user_id == user_id, Job.source == source_key, Job.external_id == external_id)
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        existing = _result_first(result)
        if existing:
            return existing

    normalized_url = _canonical_job_url(url)
    if normalized_url:
        filters = [Job.user_id == user_id, Job.url.is_not(None)]
        if source_key:
            filters.append(Job.source == source_key)
        result = await db.execute(
            select(Job)
            .where(*filters)
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
    """Score a job against the user's profile using the enhanced scorer.

    Delegates to match_scoring.score_job for multi-axis algorithmic matching
    with skill synonyms, word-boundary matching, experience relevance, etc.

    Returns:
        (score 0-100, breakdown dict)
    """
    from app.services.match_scoring import score_job  # noqa: PLC0415
    return score_job(job_data, profile)


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
                 Options: jsearch, adzuna, remotive, jobicy, dice, simplify, newgrad,
                 yc_jobs, wellfound, ventureloop
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
        # newgrad-jobs.com serves ~100 jobs per category across 5 categories.
        # Let it pull all available instead of capping to the generic limit.
        raw_jobs.extend(await newgrad_jobs_client.search_newgrad_jobs(
            query=query,
        ))
    if "yc_jobs" in all_sources:
        raw_jobs.extend(await yc_jobs_client.search_yc_jobs(query=query, limit=max(limit, 50)))
    if "wellfound" in all_sources:
        raw_jobs.extend(await wellfound_jobs_client.search_wellfound_jobs(query=query, limit=max(limit, 50)))
    if "ventureloop" in all_sources:
        raw_jobs.extend(await ventureloop_jobs_client.search_ventureloop_jobs(query=query, limit=max(limit, 100)))

    # Deduplicate and store
    stored_jobs: list[Job] = []
    seen_job_keys: set[str] = set()
    known_startup_companies = (
        await _load_known_startup_company_names(db, user_id) if raw_jobs else set()
    )

    for data in raw_jobs:
        _infer_startup_tags_for_job(data, known_startup_companies)
        fp = _fingerprint(
            data.get("company_name", ""),
            data.get("title", ""),
            data.get("location", ""),
        )
        job_key = _job_identity_key(data, fingerprint=fp)

        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)

        existing = await _find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source"),
            ats=data.get("ats"),
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )

        score, breakdown = _score_job(data, profile)
        experience_level = _experience_level_for_job(data)

        if existing:
            _refresh_existing_job(
                existing,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            continue

        job = _build_job(
            user_id=user_id,
            data=data,
            score=score,
            breakdown=breakdown,
            fingerprint=fp,
        )
        db.add(job)
        stored_jobs.append(job)

    # Auto-save search preference for Celery auto-refresh
    pref_stmt = select(SearchPreference).where(
        SearchPreference.user_id == user_id,
        SearchPreference.query == query.strip(),
        SearchPreference.mode == "default",
    )
    pref_result = await db.execute(pref_stmt)
    existing_pref = pref_result.scalar_one_or_none()
    if not existing_pref:
        db.add(SearchPreference(
            user_id=user_id,
            query=query.strip(),
            location=location,
            remote_only=remote_only,
            mode="default",
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
    *,
    extra_tags: list[str] | None = None,
    include_existing_exact_matches: bool = True,
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
    for raw_data in raw_jobs:
        data = _with_extra_tags(raw_data, extra_tags)
        fp = _fingerprint(data.get("company_name", ""), data["title"], data.get("location", ""))
        job_key = _job_identity_key(data, fingerprint=fp)
        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)

        job_ats = data.get("ats", ats_type)
        job_ats_slug = data.get("ats_slug", company_slug)
        score, breakdown = _score_job(data, profile)
        experience_level = _experience_level_for_job(data)
        existing_job = await _find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source", ats_type),
            ats=job_ats,
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )
        if existing_job:
            if exact_job_lookup or extra_tags:
                _refresh_existing_job(
                    existing_job,
                    data,
                    fingerprint=fp,
                    score=score,
                    breakdown=breakdown,
                    experience_level=experience_level,
                )
            board_jobs.append(existing_job)
            continue

        job = _build_job(
            user_id=user_id,
            data={
                **data,
                "company_name": data.get("company_name", company_slug),
                "source": data.get("source", ats_type),
                "ats": job_ats,
                "ats_slug": job_ats_slug,
            },
            score=score,
            breakdown=breakdown,
            fingerprint=fp,
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

    if not include_existing_exact_matches:
        stored_ids = {job.id for job in stored_jobs}
        return [job for job in exact_matches if job.id in stored_ids]

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
    experience_level: str | None = None,
    salary_min: float | None = None,
    remote: bool | None = None,
    startup: bool | None = None,
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
    if experience_level:
        query = query.where(Job.experience_level == experience_level)
    if salary_min is not None:
        query = query.where(Job.salary_max >= salary_min)
    if remote is not None:
        query = query.where(Job.remote == remote)
    if startup is not None:
        if startup:
            query = query.where(Job.tags.contains([STARTUP_TAG]))
        else:
            query = query.where(or_(Job.tags.is_(None), not_(Job.tags.contains([STARTUP_TAG]))))
    if search:
        term = f"%{search}%"
        query = query.where(
            Job.title.ilike(term) | Job.company_name.ilike(term)
        )

    if sort_by == "score":
        query = query.order_by(Job.match_score.desc().nullslast())
    elif sort_by == "date":
        # Sort by the actual posting date when available, fall back to created_at
        query = query.order_by(
            sa_func.coalesce(Job.posted_at, Job.created_at.cast(String)).desc()
        )
    else:
        query = query.order_by(
            sa_func.coalesce(Job.posted_at, Job.created_at.cast(String)).desc()
        )

    return await paginate(db, query, limit=limit, offset=offset)


async def update_job_stage(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    stage: str,
    notes: str | None = None,
) -> Job:
    """Update a job's kanban stage."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    old_stage = job.stage
    job.stage = stage
    if notes is not None:
        job.notes = notes

    # Auto-set applied_at when moving to 'applied' for the first time
    if stage == "applied" and old_stage != "applied" and not job.applied_at:
        job.applied_at = _dt.now(_tz.utc)

    await db.commit()
    await db.refresh(job)

    # Auto-draft outreach when moving to 'applied' (if enabled)
    if stage == "applied" and old_stage != "applied":
        try:
            from app.services.settings_service import get_auto_prospect  # noqa: PLC0415

            auto_settings = await get_auto_prospect(db, user_id)
            if auto_settings.get("auto_draft_on_apply"):
                from app.tasks.auto_prospect import auto_draft_for_job  # noqa: PLC0415
                auto_draft_for_job.delay(str(user_id), str(job_id))
                logger.info(
                    "Auto-draft queued on apply: user=%s job=%s", user_id, job_id,
                )
        except Exception:
            logger.debug("Auto-draft trigger check failed", exc_info=True)

    return job


async def update_interview_rounds(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    rounds: list[dict],
) -> Job:
    """Update a job's interview rounds (full replacement)."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.interview_rounds = rounds
    await db.commit()
    await db.refresh(job)
    return job


async def update_offer_details(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    offer: dict,
) -> Job:
    """Update a job's offer details."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.offer_details = offer
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


async def get_job_command_center(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict | None:
    """Build a compact command-center summary for a single saved job."""
    job = await get_job(db, user_id, job_id)
    if not job:
        return None

    normalized_company = normalize_company_name(job.company_name)
    now = datetime.now(timezone.utc)

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    contacts_result = await db.execute(
        select(Person)
        .join(Company, Person.company_id == Company.id)
        .where(
            Person.user_id == user_id,
            Company.user_id == user_id,
            Company.normalized_name == normalized_company,
        )
        .order_by(
            Person.current_company_verified.desc().nullslast(),
            Person.email_verified.desc().nullslast(),
            Person.relevance_score.desc().nullslast(),
            Person.created_at.desc(),
        )
        .options(selectinload(Person.company))
    )
    contacts = list(contacts_result.scalars().all())
    top_contacts = contacts[:4]

    tailored_result = await db.execute(
        select(TailoredResume.id)
        .where(
            TailoredResume.user_id == user_id,
            TailoredResume.job_id == job_id,
        )
        .limit(1)
    )
    has_tailored_resume = tailored_result.scalar_one_or_none() is not None

    artifact_result = await db.execute(
        select(ResumeArtifact.id)
        .where(
            ResumeArtifact.user_id == user_id,
            ResumeArtifact.job_id == job_id,
        )
        .limit(1)
    )
    has_resume_artifact = artifact_result.scalar_one_or_none() is not None

    messages_result = await db.execute(
        select(Message, Person)
        .join(Person, Message.person_id == Person.id)
        .where(
            Message.user_id == user_id,
            Message.context_snapshot["job_id"].astext == str(job_id),
        )
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    recent_messages_rows = messages_result.all()

    outreach_result = await db.execute(
        select(OutreachLog)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.job_id == job_id,
        )
        .options(selectinload(OutreachLog.person), selectinload(OutreachLog.job))
        .order_by(OutreachLog.updated_at.desc())
    )
    outreach_logs = list(outreach_result.scalars().all())
    recent_outreach = outreach_logs[:5]

    verified_contacts_count = sum(1 for person in contacts if person.current_company_verified)
    reachable_contacts_count = sum(1 for person in contacts if person.work_email or person.linkedin_url)
    active_outreach_count = sum(
        1 for log in outreach_logs if log.status in {"sent", "connected", "following_up"}
    )
    responded_outreach_count = sum(
        1 for log in outreach_logs if log.response_received or log.status in {"responded", "met", "closed"}
    )
    due_follow_ups_count = sum(
        1
        for log in outreach_logs
        if log.next_follow_up_at is not None
        and log.next_follow_up_at <= now
        and log.status != "closed"
    )

    checklist = {
        "resume_uploaded": bool(profile and profile.resume_parsed),
        "match_scored": job.match_score is not None,
        "resume_tailored": has_tailored_resume,
        "resume_artifact_generated": has_resume_artifact,
        "contacts_saved": len(contacts) > 0,
        "outreach_started": len(outreach_logs) > 0,
        "applied": job.stage in {"applied", "interviewing", "offer", "accepted", "rejected", "withdrawn"},
        "interview_rounds_logged": bool(job.interview_rounds),
    }

    stats = {
        "saved_contacts_count": len(contacts),
        "verified_contacts_count": verified_contacts_count,
        "reachable_contacts_count": reachable_contacts_count,
        "drafted_messages_count": len(recent_messages_rows),
        "outreach_count": len(outreach_logs),
        "active_outreach_count": active_outreach_count,
        "responded_outreach_count": responded_outreach_count,
        "due_follow_ups_count": due_follow_ups_count,
    }

    snapshot = await get_job_research_snapshot(db, user_id=user_id, job_id=job_id)
    research_snapshot = serialize_snapshot(snapshot)

    next_action = _determine_job_next_action(
        job=job,
        checklist=checklist,
        stats=stats,
        research_snapshot=research_snapshot,
    )

    return {
        "job_id": str(job.id),
        "research_snapshot": research_snapshot,
        "stage": job.stage,
        "checklist": checklist,
        "stats": stats,
        "next_action": next_action,
        "top_contacts": [
            {
                "id": str(person.id),
                "full_name": person.full_name,
                "title": person.title,
                "person_type": person.person_type,
                "work_email": person.work_email,
                "linkedin_url": person.linkedin_url,
                "email_verified": bool(person.email_verified),
                "current_company_verified": person.current_company_verified,
            }
            for person in top_contacts
        ],
        "recent_messages": [
            {
                "id": str(message.id),
                "person_id": str(person.id),
                "person_name": person.full_name,
                "channel": message.channel,
                "goal": message.goal,
                "status": message.status,
                "created_at": message.created_at.isoformat(),
            }
            for message, person in recent_messages_rows
        ],
        "recent_outreach": [
            {
                "id": str(log.id),
                "person_id": str(log.person_id),
                "person_name": log.person.full_name if log.person else None,
                "channel": log.channel,
                "status": log.status,
                "response_received": log.response_received,
                "last_contacted_at": log.last_contacted_at.isoformat() if log.last_contacted_at else None,
                "next_follow_up_at": log.next_follow_up_at.isoformat() if log.next_follow_up_at else None,
                "created_at": log.created_at.isoformat(),
            }
            for log in recent_outreach
        ],
    }


def _determine_job_next_action(
    *,
    job: Job,
    checklist: dict,
    stats: dict,
    research_snapshot: dict | None = None,
) -> dict:
    """Return the single highest-leverage next action for the job command center."""
    has_live_targets = bool(research_snapshot and research_snapshot.get("total_candidates", 0) > 0)
    if not checklist["resume_uploaded"]:
        return {
            "key": "upload_resume",
            "title": "Upload your resume first",
            "detail": "Resume-backed scoring and tailoring are unavailable until your profile has a parsed resume.",
            "cta_label": "Open Profile",
            "cta_section": "profile",
        }

    if not checklist["contacts_saved"] and not has_live_targets:
        return {
            "key": "find_people",
            "title": "Find people at this company",
            "detail": "You do not have saved or fresh recruiter, hiring manager, or peer matches for this role yet.",
            "cta_label": "Find People",
            "cta_section": "people",
        }

    if (
        has_live_targets
        and stats["outreach_count"] == 0
        and job.stage in {"discovered", "interested", "researching", "networking"}
    ):
        total = research_snapshot["total_candidates"] if research_snapshot else 0
        return {
            "key": "draft_live_outreach",
            "title": "Work the saved people-search results",
            "detail": (
                f"You have {total} live candidate{'s' if total != 1 else ''} stored from your latest "
                "people search. Convert that targeting into outreach."
            ),
            "cta_label": "Draft Message",
            "cta_section": "people",
        }

    if stats["due_follow_ups_count"] > 0:
        return {
            "key": "follow_up_due",
            "title": "Review overdue follow-ups",
            "detail": "At least one job-linked outreach thread is due for follow-up now.",
            "cta_label": "Review Outreach",
            "cta_section": "activity",
        }

    if not checklist["resume_tailored"] and checklist["match_scored"]:
        return {
            "key": "tailor_resume",
            "title": "Tailor your resume for this role",
            "detail": "You have a scored job but no saved tailoring suggestions for this application yet.",
            "cta_label": "Tailor Resume",
            "cta_section": "resume",
        }

    if checklist["resume_tailored"] and not checklist["resume_artifact_generated"] and job.stage in {"discovered", "interested", "researching", "networking", "applied"}:
        return {
            "key": "generate_resume_artifact",
            "title": "Generate a submission-ready resume variant",
            "detail": "Tailoring suggestions exist, but you have not saved a concrete resume artifact for this role yet.",
            "cta_label": "Generate Resume",
            "cta_section": "resume",
        }

    if job.stage in {"interviewing", "offer"} and not checklist["interview_rounds_logged"]:
        return {
            "key": "log_interviews",
            "title": "Log interview rounds",
            "detail": "Interview stage is active, but no rounds are saved on this job yet.",
            "cta_label": "Update Tracker",
            "cta_section": "stage",
        }

    if job.stage in {"discovered", "interested", "researching", "networking"} and stats["outreach_count"] == 0:
        return {
            "key": "draft_first_outreach",
            "title": "Draft your first message",
            "detail": "You already have company contacts saved for this role, but no outreach has been logged yet.",
            "cta_label": "Open Messages",
            "cta_section": "activity",
        }

    if job.stage == "applied" and stats["outreach_count"] == 0:
        return {
            "key": "post_apply_outreach",
            "title": "Start post-apply outreach",
            "detail": "This role is already in the pipeline, but no recruiter, hiring manager, or peer contact has been logged for it yet.",
            "cta_label": "Open Messages",
            "cta_section": "activity",
        }

    return {
        "key": "review_job",
        "title": "Keep this job moving",
        "detail": "The core workflow is in place. Review activity, update stage, or re-run people search if the context has changed.",
        "cta_label": "Review Activity",
        "cta_section": "activity",
    }


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

# Curated ATS boards to pull from during discovery.
# These are popular tech companies with public Greenhouse/Ashby boards.
ATS_DISCOVER_BOARDS: list[dict[str, str]] = [
    # Greenhouse
    {"slug": "stripe", "ats": "greenhouse"},
    {"slug": "airbnb", "ats": "greenhouse"},
    {"slug": "figma", "ats": "greenhouse"},
    {"slug": "coinbase", "ats": "greenhouse"},
    {"slug": "robinhood", "ats": "greenhouse"},
    {"slug": "databricks", "ats": "greenhouse"},
    {"slug": "discord", "ats": "greenhouse"},
    {"slug": "brex", "ats": "greenhouse"},
    {"slug": "doordash", "ats": "greenhouse"},
    {"slug": "plaid", "ats": "greenhouse"},
    {"slug": "duolingo", "ats": "greenhouse"},
    {"slug": "squarespace", "ats": "greenhouse"},
    {"slug": "relativityspace", "ats": "greenhouse"},
    {"slug": "airtable", "ats": "greenhouse"},
    {"slug": "zscaler", "ats": "greenhouse"},
    {"slug": "instacart", "ats": "greenhouse"},
    {"slug": "scaleai", "ats": "greenhouse"},
    {"slug": "twitch", "ats": "greenhouse"},
    {"slug": "affirm", "ats": "greenhouse"},
    {"slug": "epicgames", "ats": "greenhouse"},
    {"slug": "roblox", "ats": "greenhouse"},
    {"slug": "postman", "ats": "greenhouse"},
    {"slug": "vercel", "ats": "greenhouse"},
    {"slug": "roku", "ats": "greenhouse"},
    {"slug": "gusto", "ats": "greenhouse"},
    {"slug": "jfrog", "ats": "greenhouse"},
    {"slug": "block", "ats": "greenhouse"},
    {"slug": "toast", "ats": "greenhouse"},
    {"slug": "spacex", "ats": "greenhouse"},
    {"slug": "marqeta", "ats": "greenhouse"},
    {"slug": "anthropic", "ats": "greenhouse"},
    {"slug": "asana", "ats": "greenhouse"},
    {"slug": "stabilityai", "ats": "greenhouse"},
    {"slug": "pinterest", "ats": "greenhouse"},
    {"slug": "togetherai", "ats": "greenhouse"},
    {"slug": "reddit", "ats": "greenhouse"},
    {"slug": "lucidmotors", "ats": "greenhouse"},
    {"slug": "dropbox", "ats": "greenhouse"},
    {"slug": "twilio", "ats": "greenhouse"},
    {"slug": "datadog", "ats": "greenhouse"},
    {"slug": "cloudflare", "ats": "greenhouse"},
    {"slug": "betterment", "ats": "greenhouse"},
    {"slug": "webflow", "ats": "greenhouse"},
    {"slug": "elastic", "ats": "greenhouse"},
    {"slug": "chime", "ats": "greenhouse"},
    {"slug": "flexport", "ats": "greenhouse"},
    {"slug": "billcom", "ats": "greenhouse"},
    {"slug": "gitlab", "ats": "greenhouse"},
    {"slug": "linkedin", "ats": "greenhouse"},
    {"slug": "mongodb", "ats": "greenhouse"},
    {"slug": "lyft", "ats": "greenhouse"},
    {"slug": "okta", "ats": "greenhouse"},
    {"slug": "waymo", "ats": "greenhouse"},
    {"slug": "andurilindustries", "ats": "greenhouse"},
    {"slug": "samsara", "ats": "greenhouse"},
    {"slug": "uberfreight", "ats": "greenhouse"},
    {"slug": "grammarly", "ats": "greenhouse"},
    {"slug": "verkada", "ats": "greenhouse"},
    {"slug": "niantic", "ats": "greenhouse"},
    {"slug": "nuro", "ats": "greenhouse"},
    {"slug": "canva", "ats": "greenhouse"},
    {"slug": "wiz", "ats": "greenhouse"},
    {"slug": "snyk", "ats": "greenhouse"},
    {"slug": "applovin", "ats": "greenhouse"},
    {"slug": "coreweave", "ats": "greenhouse"},
    # Ashby
    {"slug": "ramp", "ats": "ashby"},
    {"slug": "notion", "ats": "ashby"},
    {"slug": "openai", "ats": "ashby"},
    {"slug": "linear", "ats": "ashby"},
    {"slug": "cursor", "ats": "ashby"},
    {"slug": "snowflake", "ats": "ashby"},
    {"slug": "cohere", "ats": "ashby"},
    {"slug": "clickup", "ats": "ashby"},
    {"slug": "zapier", "ats": "ashby"},
    {"slug": "runway", "ats": "ashby"},
    {"slug": "deel", "ats": "ashby"},
    {"slug": "vanta", "ats": "ashby"},
    {"slug": "plaid", "ats": "ashby"},
    {"slug": "elevenlabs", "ats": "ashby"},
    {"slug": "replit", "ats": "ashby"},
    {"slug": "perplexity", "ats": "ashby"},
    {"slug": "ashby", "ats": "ashby"},
    {"slug": "deepgram", "ats": "ashby"},
    {"slug": "confluent", "ats": "ashby"},
    {"slug": "benchling", "ats": "ashby"},
    {"slug": "supabase", "ats": "ashby"},
    {"slug": "sentry", "ats": "ashby"},
    {"slug": "sanity", "ats": "ashby"},
    {"slug": "modal", "ats": "ashby"},
    {"slug": "lambda", "ats": "ashby"},
    {"slug": "astronomer", "ats": "ashby"},
    {"slug": "drata", "ats": "ashby"},
    {"slug": "livekit", "ats": "ashby"},
    {"slug": "atlan", "ats": "ashby"},
    {"slug": "render", "ats": "ashby"},
    {"slug": "posthog", "ats": "ashby"},
    {"slug": "anyscale", "ats": "ashby"},
    {"slug": "neon", "ats": "ashby"},
    {"slug": "resend", "ats": "ashby"},
    {"slug": "railway", "ats": "ashby"},
    {"slug": "airbyte", "ats": "ashby"},
]

# Lever companies (scraped from HTML since the API is deprecated)
LEVER_DISCOVER_SLUGS = [
    "spotify",
    "matchgroup",
    "palantir",
    "plaid",
    "ro",
    "outreach",
    "toptal",
    "jumpcloud",
    "greenlight",
    "wealthfront",
    "matillion",
]


async def _discover_ats_boards(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit_per_board: int = 50,
) -> int:
    """Pull jobs from curated Greenhouse, Ashby, Lever, and Workday boards."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    total_new = 0

    # --- Greenhouse + Ashby (API-based) ---
    for board in ATS_DISCOVER_BOARDS:
        try:
            stored = await search_ats_jobs(
                db,
                user_id,
                company_slug=board["slug"],
                ats_type=board["ats"],
                limit=limit_per_board,
            )
            if stored:
                logger.info(
                    "ATS discover %s/%s: %d new jobs",
                    board["ats"], board["slug"], len(stored),
                )
            total_new += len(stored)
        except Exception:
            logger.exception(
                "ATS discover failed for %s/%s", board["ats"], board["slug"]
            )

    # --- Lever (HTML scraping) ---
    for slug in LEVER_DISCOVER_SLUGS:
        try:
            raw_jobs = await lever_scrape_client.search_lever_html(slug, limit=limit_per_board)
            stored = await _store_raw_jobs(db, user_id, raw_jobs, profile)
            if stored:
                logger.info("Lever discover %s: %d new jobs", slug, len(stored))
            total_new += len(stored)
        except Exception:
            logger.exception("Lever discover failed for %s", slug)

    # --- Workday (hidden JSON API) ---
    try:
        raw_jobs = await workday_client.discover_all_workday(limit_per_company=20)
        stored = await _store_raw_jobs(db, user_id, raw_jobs, profile)
        if stored:
            logger.info("Workday discover: %d new jobs", len(stored))
        total_new += len(stored)
    except Exception:
        logger.exception("Workday discover failed")

    # --- Proprietary career sites (best-effort) ---
    proprietary_sources: list[tuple[str, object]] = [
        ("Amazon", amazon_client.search_amazon_jobs),
        ("Microsoft", microsoft_client.search_microsoft_jobs),
        ("Apple", apple_client.search_apple_jobs),
        ("Google", google_client.search_google_jobs),
        ("Tesla", tesla_client.search_tesla_jobs),
        ("Meta", meta_client.search_meta_jobs),
    ]
    for source_label, fetcher in proprietary_sources:
        try:
            raw_jobs = await fetcher(limit=20)
            stored = await _store_raw_jobs(db, user_id, raw_jobs, profile)
            if stored:
                logger.info("%s discover: %d new jobs", source_label, len(stored))
            total_new += len(stored)
        except Exception:
            logger.exception("%s discover failed", source_label)

    return total_new


async def _load_known_startup_company_names(
    db: AsyncSession, user_id: uuid.UUID
) -> set[str]:
    """Return the lowercased company names this user already has startup jobs for.

    Used by ``_infer_startup_tags_for_job`` to tag new postings from the same
    company even when they arrive via non-startup ingestion paths (e.g. a YC
    company posting via Greenhouse).
    """
    try:
        stmt = (
            select(sa_func.lower(Job.company_name))
            .where(
                Job.user_id == user_id,
                Job.tags.contains([STARTUP_TAG]),
            )
            .distinct()
        )
        result = await db.execute(stmt)
        return {row.strip() for row in result.scalars().all() if row}
    except Exception:
        logger.debug("known-startup company lookup failed", exc_info=True)
        return set()


def _infer_startup_tags_for_job(
    data: dict, known_startup_companies: set[str]
) -> None:
    """If a job's company is a known startup, merge inferred startup tags in-place.

    Skips jobs that already carry authoritative startup tags from their
    source-based ingestion path.
    """
    tags = data.get("tags") or []
    if has_startup_tag(tags):
        return
    company = (data.get("company_name") or "").strip().lower()
    if not company or company not in known_startup_companies:
        return
    inferred = [STARTUP_TAG, startup_source_tag("inferred")]
    data["tags"] = merge_tags(tags, inferred)


async def _store_raw_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    raw_jobs: list[dict],
    profile: Profile | None,
) -> list[Job]:
    """Deduplicate and store raw job dicts from any source."""
    stored: list[Job] = []
    seen_job_keys: set[str] = set()
    known_startup_companies = (
        await _load_known_startup_company_names(db, user_id) if raw_jobs else set()
    )

    for data in raw_jobs:
        _infer_startup_tags_for_job(data, known_startup_companies)
        fp = _fingerprint(data.get("company_name", ""), data.get("title", ""), data.get("location", ""))
        job_key = _job_identity_key(data, fingerprint=fp)
        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)

        existing = await _find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source"),
            ats=data.get("ats"),
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )
        score, breakdown = _score_job(data, profile)
        experience_level = _experience_level_for_job(data)
        if existing:
            _refresh_existing_job(
                existing,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            continue

        job = _build_job(
            user_id=user_id,
            data=data,
            score=score,
            breakdown=breakdown,
            fingerprint=fp,
        )
        db.add(job)
        stored.append(job)

    if stored:
        await db.commit()

        # Trigger auto-prospect for newly stored jobs (if enabled)
        try:
            await _maybe_auto_prospect(db, user_id, stored)
        except Exception:
            logger.debug("Auto-prospect trigger check failed", exc_info=True)

    return stored


async def _maybe_auto_prospect(
    db: AsyncSession,
    user_id: uuid.UUID,
    jobs: list,
) -> None:
    """Queue auto-prospect Celery tasks for new jobs if the user has it enabled."""
    from app.services.settings_service import is_auto_prospect_enabled  # noqa: PLC0415

    for job in jobs:
        company = getattr(job, "company_name", None) or ""
        if not await is_auto_prospect_enabled(db, user_id, company):
            continue
        try:
            from app.tasks.auto_prospect import auto_prospect_job  # noqa: PLC0415
            auto_prospect_job.delay(str(user_id), str(job.id))
            logger.info(
                "Auto-prospect queued: user=%s job=%s company=%s",
                user_id, job.id, company,
            )
        except Exception:
            logger.debug("Failed to queue auto-prospect task", exc_info=True)


async def _resolve_supported_job_links(url: str, *, max_depth: int = 1) -> list[str]:
    if is_supported_job_link(url):
        return [url]

    visited_pages: set[str] = set()
    queue: list[tuple[str, int]] = [(url, 0)]
    resolved: list[str] = []
    seen_links: set[str] = set()

    while queue:
        page_url, depth = queue.pop(0)
        if page_url in visited_pages:
            continue
        visited_pages.add(page_url)

        page = await public_page_client.fetch_direct_page(page_url, timeout_seconds=15)
        if not page or not page.get("html"):
            continue

        for candidate in extract_candidate_links(str(page.get("url") or page_url), str(page.get("html") or "")):
            if candidate in seen_links:
                continue
            seen_links.add(candidate)
            if is_supported_job_link(candidate):
                resolved.append(candidate)
            elif depth < max_depth and looks_like_careers_page(candidate):
                queue.append((candidate, depth + 1))

    return resolved


async def _discover_startup_direct_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    queries: list[str],
) -> int:
    raw_jobs: list[dict] = []
    fetchers = [
        ("yc_jobs", yc_jobs_client.search_yc_jobs),
        ("wellfound", wellfound_jobs_client.search_wellfound_jobs),
        ("ventureloop", ventureloop_jobs_client.search_ventureloop_jobs),
    ]

    results = await asyncio.gather(
        *(fetcher(limit=200) for _, fetcher in fetchers),
        return_exceptions=True,
    )
    for (source_key, _fetcher), result in zip(fetchers, results):
        if isinstance(result, BaseException):
            logger.error("Startup direct source failed: %s", source_key, exc_info=result)
        else:
            raw_jobs.extend(result)

    matching_jobs = [job for job in raw_jobs if job_matches_any_query(job, queries)]
    stored = await _store_raw_jobs(db, user_id, matching_jobs, profile)
    return len(stored)


async def _import_startup_candidate_link(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    *,
    startup_source: str,
    candidate_url: str,
    queries: list[str],
) -> int:
    parsed = ats_client.parse_ats_job_url(candidate_url)
    if not parsed:
        return 0

    if (
        parsed.company_slug
        and parsed.external_id is None
        and parsed.exact_url_only is False
        and parsed.ats_type in {"greenhouse", "lever", "ashby"}
    ):
        adapter = ats_client.get_adapter(parsed.ats_type)
        if adapter is None or adapter.search_board is None:
            return 0
        raw_jobs = await adapter.search_board(parsed.company_slug, None)
        tagged_jobs = [
            append_startup_tags(job, startup_source)
            for job in raw_jobs
            if job_matches_any_query(job, queries)
        ]
        stored = await _store_raw_jobs(db, user_id, tagged_jobs, profile)
        return len(stored)

    exact_jobs = await search_ats_jobs(
        db,
        user_id,
        company_slug=None,
        ats_type=None,
        job_url=candidate_url,
        extra_tags=startup_tags(startup_source),
        include_existing_exact_matches=False,
    )
    return len(exact_jobs)


async def _discover_startup_ecosystem_entries(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    *,
    entries: list[dict],
    url_key: str,
    startup_source: str,
    queries: list[str],
) -> int:
    semaphore = asyncio.Semaphore(STARTUP_LINK_RESOLVE_CONCURRENCY)

    async def _process_entry(entry: dict) -> int:
        raw_url = str(entry.get(url_key) or "").strip()
        if not raw_url:
            return 0

        # Entries with roles (e.g. Conviction) are pre-filtered here.
        # Entries without roles (e.g. Speedrun companies) intentionally skip
        # this filter — role queries can't match bare company names, and the
        # real query filtering happens downstream in _import_startup_candidate_link.
        roles = entry.get("roles") or []
        if roles:
            matches_role = any(
                job_matches_any_query(
                    {
                        "title": role.get("title"),
                        "location": role.get("location"),
                        "company_name": entry.get("company_name"),
                    },
                    queries,
                )
                for role in roles
                if isinstance(role, dict)
            )
            if not matches_role:
                return 0

        async with semaphore:
            links = await _resolve_supported_job_links(raw_url)

        total_new = 0
        for candidate in links[:STARTUP_MAX_RESOLVED_LINKS_PER_COMPANY]:
            try:
                total_new += await _import_startup_candidate_link(
                    db,
                    user_id,
                    profile,
                    startup_source=startup_source,
                    candidate_url=candidate,
                    queries=queries,
                )
            except Exception:
                logger.exception(
                    "Failed importing startup candidate link from %s: %s",
                    startup_source,
                    candidate,
                )
        return total_new

    if not entries:
        return 0

    counts = await asyncio.gather(*(_process_entry(entry) for entry in entries))
    return sum(counts)


async def _discover_startup_ecosystems(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    queries: list[str],
) -> int:
    total_new = 0

    try:
        conviction_entries = await conviction_jobs_client.fetch_conviction_startups()
        total_new += await _discover_startup_ecosystem_entries(
            db,
            user_id,
            profile,
            entries=conviction_entries,
            url_key="career_url",
            startup_source="conviction",
            queries=queries,
        )
    except Exception:
        logger.exception("Conviction startup discover failed")

    try:
        speedrun_companies = await speedrun_jobs_client.fetch_speedrun_companies(limit=100)
        total_new += await _discover_startup_ecosystem_entries(
            db,
            user_id,
            profile,
            entries=speedrun_companies,
            url_key="website_url",
            startup_source="a16z_speedrun",
            queries=queries,
        )
    except Exception:
        logger.exception("a16z Speedrun startup discover failed")

    try:
        curated_entries = curated_startups_client.get_curated_startups()
        total_new += await _discover_startup_ecosystem_entries(
            db,
            user_id,
            profile,
            entries=curated_entries,
            url_key="career_url",
            startup_source="curated_list",
            queries=queries,
        )
    except Exception:
        logger.exception("Curated startups list discover failed")

    return total_new


async def run_startup_refresh_for_query(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
) -> list[Job]:
    """Re-run the startup discover flow for a single saved-search query.

    Returns the list of Job rows that were newly created by this run so the
    caller (Celery refresh task) can fire notifications. Matches the
    snapshotting approach used by ``search_jobs`` but scoped to the startup
    sources + ecosystems rather than standard job boards.
    """
    trimmed = (query or "").strip()
    if not trimmed:
        return []

    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    snapshot_time = datetime.now(timezone.utc)
    queries = [trimmed]

    try:
        await _discover_startup_direct_sources(db, user_id, profile, queries)
    except Exception:
        logger.exception("Startup refresh: direct sources failed for query '%s'", trimmed)
    try:
        await _discover_startup_ecosystems(db, user_id, profile, queries)
    except Exception:
        logger.exception("Startup refresh: ecosystems failed for query '%s'", trimmed)

    await db.commit()

    new_rows = await db.execute(
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.created_at >= snapshot_time,
        )
        .order_by(Job.created_at.desc())
    )
    return list(new_rows.scalars().all())


async def _ensure_startup_search_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str],
) -> None:
    """Persist a SearchPreference(mode="startup") per query if not already stored."""
    for raw_query in queries:
        query = (raw_query or "").strip()
        if not query:
            continue
        stmt = select(SearchPreference).where(
            SearchPreference.user_id == user_id,
            SearchPreference.query == query,
            SearchPreference.mode == "startup",
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            db.add(
                SearchPreference(
                    user_id=user_id,
                    query=query,
                    location=None,
                    remote_only=False,
                    mode="startup",
                )
            )


async def discover_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str] | None = None,
    mode: str = "default",
) -> int:
    """Run a batch of job searches across free sources and ATS boards.

    Unlike seed_default_feeds this always runs — it is the manual
    "Discover Jobs" action.  Deduplication is handled by search_jobs
    and search_ats_jobs, so repeat runs are safe.

    Args:
        queries: Optional custom list of search terms.  Falls back to
                 DISCOVER_QUERIES when not supplied.
    """
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    if mode == "startup":
        startup_queries = queries or startup_discover_queries(
            profile.target_roles if profile is not None else None
        )
        total_new = await _discover_startup_direct_sources(db, user_id, profile, startup_queries)
        total_new += await _discover_startup_ecosystems(db, user_id, profile, startup_queries)
        # Persist search preferences with mode="startup" so the hourly Celery
        # refresh can re-run the startup discover flow instead of falling back
        # to the default job-board search.
        await _ensure_startup_search_preferences(db, user_id, startup_queries)
        await db.commit()
        return total_new

    search_list = (
        [{"query": q, "location": None, "remote_only": False} for q in queries]
        if queries
        else DISCOVER_QUERIES
    )

    total_new = 0

    # 1. Standard job search (JSearch, Dice, Remotive — newgrad excluded here)
    #    newgrad is scraped once unfiltered below instead of 7× with keyword filters
    #    that would discard most results.
    for seed in search_list:
        try:
            stored = await search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
                sources=["jsearch", "adzuna", "remotive", "dice"],
            )
            total_new += len(stored)
        except Exception:
            logger.exception("Discover failed for query: %s", seed["query"])

    # 2. newgrad-jobs.com — single unfiltered scrape across all 5 categories
    #    (~500 unique jobs).  Deduplication is handled by _store_raw_jobs.
    try:
        raw_newgrad = await newgrad_jobs_client.search_newgrad_jobs()
        ng_stored = await _store_raw_jobs(db, user_id, raw_newgrad, profile)
        if ng_stored:
            logger.info("newgrad-jobs discover: %d new jobs", len(ng_stored))
        total_new += len(ng_stored)
    except Exception:
        logger.exception("newgrad-jobs discover failed")

    # 3. ATS board discovery (Greenhouse, Ashby, Lever, Workday)
    try:
        ats_new = await _discover_ats_boards(db, user_id)
        total_new += ats_new
    except Exception:
        logger.exception("ATS board discovery failed")

    logger.info("Discovered %d new jobs for user %s", total_new, user_id)
    return total_new
