"""Aggregator + ATS querying: search_jobs, search_ats_jobs, apply-URL repair."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.job import Job
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
from app.services.occupation_taxonomy import (
    classify_title,
    occupation_by_key,
    occupation_keys_from_tags,
)


logger = logging.getLogger(__name__)


def _occupation_relevance(
    data: dict, occupation_hint: str | None
) -> tuple[bool, str, list[str]]:
    """Decide whether a targeted-search result is safe to persist.

    Query text is provenance, not evidence. A result must be supported by a
    trusted explicit source tag or by title/description classification.
    """
    if not occupation_hint:
        return True, "untargeted", []
    requested = occupation_by_key(occupation_hint)
    if requested is None:
        return False, "invalid_requested_occupation", []

    raw_tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    explicit = occupation_keys_from_tags(raw_tags)
    if requested.key in explicit:
        return True, "explicit_source_tag", explicit

    classified = classify_title(data.get("title"), data.get("description"))
    if requested.key in classified:
        return True, "content_classification", classified
    if classified:
        return False, "off_category", classified
    return False, "unclassified", []


def _record_accepted_job_quality(stat: dict, data: dict) -> None:
    """Accumulate usefulness signals, not only source availability counts."""
    details = dict(stat.get("details") or {})
    details["accepted_count"] = int(details.get("accepted_count") or 0) + 1
    field_map = {
        "with_description": bool(data.get("description")),
        "with_direct_apply": bool(data.get("apply_url")),
        "with_posted_date": bool(data.get("posted_at")),
        "with_salary": data.get("salary_min") is not None or data.get("salary_max") is not None,
        "with_location": bool(data.get("location") or data.get("locations")),
    }
    for key, present in field_map.items():
        if present:
            details[key] = int(details.get(key) or 0) + 1
    stat["details"] = details


async def _dispatch_source_fetch(
    source: str,
    *,
    query: str,
    location: str | None,
    remote_only: bool,
    limit: int,
    occupation: str | None,
) -> list[dict]:
    """Run a single aggregator's fetch and return its raw job dicts.

    Split out from ``_fetch_jobs_for_source`` so the call can be wrapped in
    ``asyncio.wait_for`` — no single slow/hung source can stall the whole
    ``search_jobs`` gather (and the interactive search request) anymore.
    """
    if source == "jsearch":
        return await jsearch_client.search_jobs(
            query, location=location, remote_only=remote_only, limit=limit
        )
    if source == "adzuna":
        return await adzuna_client.search_jobs(
            query,
            location=location,
            country=normalize._adzuna_country_for_location(location),
            limit=limit,
        )
    if source == "remotive":
        return await remote_jobs_client.search_remotive(query, limit=limit)
    if source == "jobicy":
        return await remote_jobs_client.search_jobicy(query, limit=limit)
    if source == "dice":
        return await remote_jobs_client.search_dice(
            query,
            location=location,
            country_code=(
                geocode_location_query(location).country_code
                if geocode_location_query(location)
                else country_code_for_name(location)
            ),
            limit=limit,
        )
    if source == "simplify":
        # New-grad + internship curated lists (level-stamped). Capped well
        # above `limit` because the goal here is early-career *volume*.
        return await remote_jobs_client.fetch_simplify_early_career_jobs(
            limit_per_repo=max(limit, 400)
        )
    if source == "jobbank":
        return await jobbank_client.search_jobbank(
            query, location=location, limit=limit
        )
    if source == "themuse":
        return await themuse_client.search_themuse(
            query,
            occupation=occupation,
            location=location,
            remote_only=remote_only,
            limit=limit,
            # Pull dedicated entry-level + internship roles on top of the
            # all-levels results so early-career volume isn't crowded out.
            boost_early_career=True,
        )
    if source == "newgrad":
        # Respect ``limit`` here (it used to default to 500): newgrad enriches a
        # detail page per matched job, so an uncapped interactive search fanned
        # out into hundreds of sequential scrapes — the main cause of the search
        # button hanging. The deep crawl in ``discovery.py`` still uncaps it.
        return await newgrad_jobs_client.search_newgrad_jobs(query=query, limit=limit)
    if source == "yc_jobs":
        return await yc_jobs_client.search_yc_jobs(query=query, limit=max(limit, 50))
    if source == "wellfound":
        return await wellfound_jobs_client.search_wellfound_jobs(query=query, limit=max(limit, 50))
    if source == "ventureloop":
        return await ventureloop_jobs_client.search_ventureloop_jobs(query=query, limit=max(limit, 100))
    return []


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
        jobs = await asyncio.wait_for(
            _dispatch_source_fetch(
                source,
                query=query,
                location=location,
                remote_only=remote_only,
                limit=limit,
                occupation=occupation,
            ),
            timeout=constants.SOURCE_FETCH_TIMEOUT_SECONDS,
        )
        for job in jobs:
            job["_fetch_source_key"] = source
        stat["raw_count"] = len(jobs)
        normalize._finish_source_stat(stat, status="success")
        return jobs, stat
    except asyncio.TimeoutError:
        logger.warning(
            "Job source fetch timed out after %ss: %s",
            constants.SOURCE_FETCH_TIMEOUT_SECONDS,
            source,
        )
        normalize._finish_source_stat(stat, status="failed", error="timeout")
        return [], stat
    except Exception as exc:
        # A transient network failure to a best-effort third-party board is
        # expected operational noise — log at WARNING so it doesn't surface as a
        # Sentry error. Genuine bugs still go through logger.exception.
        if normalize.is_transient_fetch_error(exc):
            logger.warning("Job source fetch network error (%s): %s", source, exc)
        else:
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

    # Load user profile for scoring (detached so a rollback can't expire it and
    # make the sync scorer trigger a reload — see load_profile_for_scoring).
    profile = await storage.load_profile_for_scoring(db, user_id)

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
        relevant, relevance_reason, classified_keys = _occupation_relevance(
            data, occupation_hint
        )
        provenance = dict(data.get("metadata_provenance") or {})
        if occupation_hint:
            provenance["occupation_relevance"] = {
                "requested": occupation_hint,
                "accepted": relevant,
                "reason": relevance_reason,
                "classified_keys": classified_keys,
            }
            data["metadata_provenance"] = provenance
        if not relevant:
            stat["skipped_count"] += 1
            details = dict(stat.get("details") or {})
            details["occupation_rejected_count"] = int(
                details.get("occupation_rejected_count") or 0
            ) + 1
            stat["details"] = details
            continue
        storage._infer_startup_tags_for_job(data, known_startup_companies)
        storage._infer_occupation_tags_for_job(data)
        data = normalize_job_metadata(data)
        if not normalize._job_matches_refresh_filters(data, location=location, remote_only=remote_only):
            stat["skipped_count"] += 1
            continue
        _record_accepted_job_quality(stat, data)
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
    # no_autoflush: the store loop above leaves new Job rows pending; without
    # it this SELECT flushes them mid-lookup, and any insert failure surfaces
    # here as an opaque "Query-invoked autoflush" DBAPIError (Sentry PYTHON-15)
    # instead of at the commit below where the caller's handler rolls back.
    with db.no_autoflush:
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
    new_jobs = [
        job for job in stored_jobs if getattr(job, "_is_new_job", False)
    ]
    if new_jobs:
        await storage.finalize_new_jobs(db, user_id, new_jobs)
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

    # Detached so a rollback can't expire it (see load_profile_for_scoring).
    profile = await storage.load_profile_for_scoring(db, user_id)

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


# Sources whose listing URL differs from the real apply URL and need a
# detail-page resolution to repair it.
_APPLY_URL_REPAIR_SOURCES = ("dice", "newgrad_jobs")

# One repair task per user per window is plenty — the task itself is capped and
# repaired rows drop out of the candidate set.
_APPLY_URL_REPAIR_DEBOUNCE_SECONDS = 600


def _apply_url_repair_candidates(jobs: list[Job]) -> list[str]:
    return [
        str(job.id)
        for job in jobs
        if job.source in _APPLY_URL_REPAIR_SOURCES and not job.apply_url and job.url
    ]


async def queue_apply_url_repair(user_id: uuid.UUID, jobs: list[Job]) -> bool:
    """Queue a background apply-URL repair for the dice/newgrad rows in *jobs*.

    Replaces the old inline repair on the hot ``GET /api/jobs`` path, which
    awaited third-party detail pages inside the request. Debounced per user so
    feed polling can't fan out into repeated tasks, and fully fail-soft: a
    Redis or broker outage must never break a feed read (the UI already falls
    back to ``job.url`` for the apply link).
    """
    try:
        candidate_ids = _apply_url_repair_candidates(jobs)
        if not candidate_ids:
            return False
        from app.clients import search_cache_client  # noqa: PLC0415

        acquired = await search_cache_client.acquire_debounce(
            f"apply_url_repair:{user_id}",
            ttl_seconds=_APPLY_URL_REPAIR_DEBOUNCE_SECONDS,
        )
        if not acquired:
            return False
        from app.tasks.jobs import repair_job_apply_urls  # noqa: PLC0415

        repair_job_apply_urls.delay(
            str(user_id), candidate_ids[: 2 * constants.APPLY_URL_REPAIR_MAX_JOBS]
        )
        return True
    except Exception:
        logger.warning("Failed to queue apply-URL repair", exc_info=True)
        return False


async def _repair_missing_apply_urls(db: AsyncSession, jobs: list[Job]) -> None:
    """Resolve real apply URLs for the dice/newgrad rows whose listing URL differs
    from the apply URL, persisting only that small, capped subset.

    This deliberately does NOT persist a plain ``apply_url = url`` fallback for the
    rest of the page. ``_to_response`` already serves ``job.apply_url or job.url``
    and ingest sets ``apply_url`` at write time (storage._build_job), so copying
    ``url -> apply_url`` for every legacy row on this hot ``GET /api/jobs`` only
    dirtied up to a full page of rows and forced a large ``UPDATE`` + ``commit``.
    On a sizable feed that commit could invalidate the pooled connection mid
    request; the implicit rollback then expired every loaded row, and the *sync*
    ``_to_response`` serializer would trip a lazy reload of an expired column —
    raising ``MissingGreenlet`` and 500-ing the whole feed. Keeping only the
    dice/newgrad resolution (each capped at ``APPLY_URL_REPAIR_MAX_JOBS``) makes
    the commit small and reliable while the user-facing apply link is unchanged.
    """
    did_update = False

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

    if did_update:
        await db.commit()
