"""Aggregator + ATS querying: search_jobs, search_ats_jobs, apply-URL repair."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.job import Job
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.clients import adzuna_client
import asyncio
from app.clients import ats
from app.utils.job_metadata import country_code_for_name
from app.utils.job_metadata import geocode_location_query
from app.clients import jobbank_client
from app.clients import jsearch_client
from app.clients import newgrad_jobs_client
from app.clients import themuse_client
from app.utils.job_metadata import normalize_job_metadata
from app.clients import remote_jobs_client
from sqlalchemy import select
import uuid
from app.clients import ventureloop_jobs_client
from app.clients import wellfound_jobs_client
from app.clients import yc_jobs_client
from app.services.jobs import constants
from app.services.jobs import normalize
from app.services.jobs import storage


logger = logging.getLogger(__name__)


async def _fetch_jobs_for_source(
    source: str,
    *,
    query: str,
    location: str | None,
    remote_only: bool,
    limit: int,
    occupation: str | None = None,
) -> tuple[list[dict], dict]:
    stat = normalize._source_stat(source)
    try:
        if source == "jsearch":
            jobs = await jsearch_client.search_jobs(
                query, location=location, remote_only=remote_only, limit=limit
            )
        elif source == "adzuna":
            jobs = await adzuna_client.search_jobs(
                query,
                location=location,
                country=normalize._adzuna_country_for_location(location),
                limit=limit,
            )
        elif source == "remotive":
            jobs = await remote_jobs_client.search_remotive(query, limit=limit)
        elif source == "jobicy":
            jobs = await remote_jobs_client.search_jobicy(query, limit=limit)
        elif source == "dice":
            jobs = await remote_jobs_client.search_dice(
                query,
                location=location,
                country_code=(
                    geocode_location_query(location).country_code
                    if geocode_location_query(location)
                    else country_code_for_name(location)
                ),
                limit=limit,
            )
        elif source == "simplify":
            jobs = await remote_jobs_client.fetch_simplify_jobs(limit=limit)
        elif source == "jobbank":
            jobs = await jobbank_client.search_jobbank(
                query, location=location, limit=limit
            )
        elif source == "themuse":
            jobs = await themuse_client.search_themuse(
                query,
                occupation=occupation,
                location=location,
                remote_only=remote_only,
                limit=limit,
            )
        elif source == "newgrad":
            jobs = await newgrad_jobs_client.search_newgrad_jobs(query=query)
        elif source == "yc_jobs":
            jobs = await yc_jobs_client.search_yc_jobs(query=query, limit=max(limit, 50))
        elif source == "wellfound":
            jobs = await wellfound_jobs_client.search_wellfound_jobs(query=query, limit=max(limit, 50))
        elif source == "ventureloop":
            jobs = await ventureloop_jobs_client.search_ventureloop_jobs(query=query, limit=max(limit, 100))
        else:
            jobs = []
            stat["details"] = {"skipped_reason": "unknown_source"}

        for job in jobs:
            job["_fetch_source_key"] = source
        stat["raw_count"] = len(jobs)
        normalize._finish_source_stat(stat, status="success")
        return jobs, stat
    except Exception as exc:
        logger.exception("Job source fetch failed: %s", source)
        normalize._finish_source_stat(stat, status="failed", error=str(exc))
        return [], stat


async def search_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    location: str | None = None,
    remote_only: bool = False,
    sources: list[str] | None = None,
    limit: int = 20,
    refresh_run_id: uuid.UUID | None = None,
    source_stats: list[dict] | None = None,
    occupation_hint: str | None = None,
) -> list[Job]:
    """Search for jobs across all sources, deduplicate, score, and store.

    Returns every job that matched this search — both newly created rows and
    existing rows that were refreshed in place. Each returned ``Job`` carries a
    transient ``_is_new_job`` flag (True for newly created rows) so the Celery
    refresh task can keep new-only counts and notifications accurate.

    Args:
        sources: List of sources to search. None = all.
                 Options: jsearch, adzuna, remotive, jobicy, dice, simplify, newgrad,
                 yc_jobs, wellfound, ventureloop, jobbank. ``jobbank`` (Canada's
                 national board) is auto-added for Canadian locations.
    """
    all_sources = sources or constants.DEFAULT_SEARCH_SOURCES
    # Job Bank is Canada's national board (all occupations, incl. non-tech) but
    # Canada-only. Add it whenever the search location is Canadian so every path
    # — discover, saved-search refresh, ad-hoc — gains it without per-call wiring,
    # and it never wastes calls on US/other locations. Fails soft to [].
    if (
        location
        and "jobbank" not in all_sources
        and normalize._adzuna_country_for_location(location) == "ca"
    ):
        all_sources = [*all_sources, "jobbank"]

    # Load user profile for scoring
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    fetch_results = await asyncio.gather(
        *(
            _fetch_jobs_for_source(
                source,
                query=query,
                location=location,
                remote_only=remote_only,
                limit=limit,
                occupation=occupation_hint,
            )
            for source in all_sources
        )
    )
    raw_jobs = [job for jobs, _ in fetch_results for job in jobs]
    local_source_stats = [stat for _, stat in fetch_results]
    stats_by_source = {stat["source"]: stat for stat in local_source_stats}

    # Deduplicate and store
    stored_jobs: list[Job] = []
    seen_job_keys: set[str] = set()
    known_startup_companies = (
        await storage._load_known_startup_company_names(db, user_id) if raw_jobs else set()
    )

    for data in raw_jobs:
        data = dict(data)
        fetch_source_key = data.pop("_fetch_source_key", None) or normalize._job_source_key(data) or "unknown"
        stat = stats_by_source.setdefault(fetch_source_key, normalize._source_stat(fetch_source_key))
        if occupation_hint:
            data.setdefault("_occupation_hint", occupation_hint)
        storage._infer_startup_tags_for_job(data, known_startup_companies)
        storage._infer_occupation_tags_for_job(data)
        data = normalize_job_metadata(data)
        if not normalize._job_matches_refresh_filters(data, location=location, remote_only=remote_only):
            stat["skipped_count"] += 1
            continue
        fp = normalize._fingerprint(
            data.get("company_name", ""),
            data.get("title", ""),
            data.get("location", ""),
        )
        job_key = normalize._job_identity_key(data, fingerprint=fp)

        if job_key in seen_job_keys:
            stat["duplicate_count"] += 1
            continue
        seen_job_keys.add(job_key)

        existing = await storage._find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source"),
            ats=data.get("ats"),
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )

        score, breakdown = storage._score_job(data, profile)
        experience_level = normalize._experience_level_for_job(data)

        if existing:
            stat["existing_count"] += 1
            storage._refresh_existing_job(
                existing,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            # Return refreshed matches too so the search endpoint shows results
            # even when every hit dedup-matched an existing row (audit C3). The
            # transient flag lets the refresh task keep "new" counts/notifications
            # scoped to genuinely new rows.
            existing._is_new_job = False  # type: ignore[attr-defined]
            stored_jobs.append(existing)
            continue

        job = storage._build_job(
            user_id=user_id,
            data=data,
            score=score,
            breakdown=breakdown,
            fingerprint=fp,
        )
        job._is_new_job = True  # type: ignore[attr-defined]
        db.add(job)
        stored_jobs.append(job)
        stat["new_count"] += 1

    # Auto-save search preference for Celery auto-refresh. Match on a normalized
    # location so "New York", "New York, NY" and "new york " don't each spawn a
    # separate hourly refresh cycle (audit M17).
    pref_stmt = select(SearchPreference).where(
        SearchPreference.user_id == user_id,
        SearchPreference.query == query.strip(),
        SearchPreference.remote_only == remote_only,
        SearchPreference.mode == "default",
    )
    pref_result = await db.execute(pref_stmt)
    target_location_key = normalize._normalized_pref_location(location)
    existing_pref = next(
        (
            pref
            for pref in pref_result.scalars().all()
            if normalize._normalized_pref_location(pref.location) == target_location_key
        ),
        None,
    )
    if not existing_pref:
        db.add(SearchPreference(
            user_id=user_id,
            query=query.strip(),
            location=location,
            remote_only=remote_only,
            mode="default",
        ))

    if source_stats is not None:
        source_stats.extend(local_source_stats)
    await storage._record_source_runs(
        db, refresh_run_id=refresh_run_id, source_stats=local_source_stats
    )
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
    parsed_job_url: ats.ParsedATSJobURL | None = None

    if job_url:
        parsed_job_url = ats.parse_ats_job_url(job_url)
        if not parsed_job_url:
            raise ValueError("Unsupported or invalid job posting URL.")
        company_slug = parsed_job_url.company_slug
        ats_type = parsed_job_url.ats_type
        target_external_id = parsed_job_url.external_id
        target_url = parsed_job_url.canonical_url

    if not ats_type:
        raise ValueError("ATS search requires either job_url or company_slug plus ats_type.")

    adapter = ats.get_adapter(ats_type)
    if not adapter:
        raise ValueError("Unsupported or invalid job posting URL.")

    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if job_url and parsed_job_url and adapter.fetch_exact is not None:
        try:
            raw_jobs = await ats.fetch_exact_job(parsed_job_url)
        except ats.ExactJobFetchError as exc:
            raise ValueError(str(exc)) from exc
    else:
        if not company_slug or adapter.search_board is None:
            raise ValueError("This job platform currently requires a direct job posting URL.")
        raw_jobs = await adapter.search_board(company_slug, limit)

    stored_jobs: list[Job] = []
    board_jobs: list[Job] = []
    seen_job_keys: set[str] = set()
    for raw_data in raw_jobs:
        data = normalize_job_metadata(normalize._with_extra_tags(raw_data, extra_tags))
        fp = normalize._fingerprint(data.get("company_name", ""), data["title"], data.get("location", ""))
        job_key = normalize._job_identity_key(data, fingerprint=fp)
        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)

        job_ats = data.get("ats", ats_type)
        job_ats_slug = data.get("ats_slug", company_slug)
        score, breakdown = storage._score_job(data, profile)
        experience_level = normalize._experience_level_for_job(data)
        existing_job = await storage._find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source", ats_type),
            ats=job_ats,
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )
        if existing_job:
            storage._refresh_existing_job(
                existing_job,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            board_jobs.append(existing_job)
            continue

        job = storage._build_job(
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

    normalized_target = normalize._canonical_job_url(target_url or job_url)
    exact_matches = [
        job
        for job in board_jobs
        if (target_external_id and job.external_id == target_external_id)
        or (normalize._canonical_job_url(job.url) and normalize._canonical_job_url(job.url) == normalized_target)
    ]
    if not exact_matches:
        return board_jobs

    if not include_existing_exact_matches:
        stored_ids = {job.id for job in stored_jobs}
        return [job for job in exact_matches if job.id in stored_ids]

    exact_ids = {job.id for job in exact_matches}
    ordered_jobs = exact_matches + [job for job in board_jobs if job.id not in exact_ids]
    return ordered_jobs


async def _repair_missing_apply_urls(db: AsyncSession, jobs: list[Job]) -> None:
    did_update = False
    for job in jobs:
        if job.source == "simplify_github" and not job.apply_url and job.url:
            job.apply_url = job.url
            did_update = True

    dice_jobs = [
        job
        for job in jobs
        if job.source == "dice" and not job.apply_url and job.url
    ][:constants.APPLY_URL_REPAIR_MAX_JOBS]

    if dice_jobs:
        resolved_urls = await remote_jobs_client.resolve_dice_apply_urls(
            [job.url for job in dice_jobs if job.url]
        )
        for job in dice_jobs:
            apply_url = resolved_urls.get(job.url or "")
            if not apply_url:
                continue
            job.apply_url = apply_url
            did_update = True

    newgrad_jobs = [
        job
        for job in jobs
        if job.source == "newgrad_jobs" and not job.apply_url and job.url
    ][:constants.APPLY_URL_REPAIR_MAX_JOBS]

    if newgrad_jobs:
        resolved_urls = await newgrad_jobs_client.resolve_newgrad_apply_urls(
            [job.url for job in newgrad_jobs if job.url]
        )
        for job in newgrad_jobs:
            apply_url = resolved_urls.get(job.url or "")
            if not apply_url:
                continue
            job.apply_url = apply_url
            did_update = True

    for job in jobs:
        if not job.apply_url and job.url:
            job.apply_url = job.url
            did_update = True

    if did_update:
        await db.commit()
