"""Job persistence: build/find/refresh rows, scoring, tagging, raw-job storage, staleness."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.job import Job
from app.models.job_refresh_run import JobSourceRun
from app.services.occupation_taxonomy import OCCUPATION_TAG_PREFIX
from app.models.profile import Profile
from app.utils.startup_jobs import STARTUP_TAG
from datetime import datetime
from app.utils.startup_jobs import has_startup_tag
from app.utils.startup_jobs import merge_startup_tags
from app.utils.startup_jobs import merge_tags
from app.utils.job_metadata import normalize_job_metadata
from app.services.occupation_taxonomy import occupation_tags_for_job
from sqlalchemy import func as sa_func
from sqlalchemy import select
from app.utils.startup_jobs import startup_source_tag
from datetime import timedelta
from datetime import timezone
from urllib.parse import urlparse
import uuid
from app.services.jobs import normalize


logger = logging.getLogger(__name__)

# Safety cap on per-job people pre-warm tasks queued from one discovery batch.
# Every new job gets people pre-warmed, but a runaway run shouldn't queue
# thousands of tasks at once. Highest-scored jobs warm first; any tail beyond
# the cap stays visible without a pre-warm (Find People still works live).
PREWARM_MAX_JOBS_PER_BATCH = 300


def _refresh_existing_job(
    job: Job,
    data: dict,
    *,
    fingerprint: str,
    score: float | None,
    breakdown: dict,
    experience_level: str,
) -> None:
    normalize._apply_if_present(job, "external_id", data.get("external_id"))
    normalize._apply_if_present(job, "title", data.get("title"))
    normalize._apply_if_present(job, "company_name", data.get("company_name"))
    normalize._apply_if_present(job, "company_logo", data.get("company_logo"))
    normalize._apply_if_present(job, "location", data.get("location"))
    # Only overwrite location/geocode fields when the refresh actually provides
    # them — otherwise a source that omits location on re-fetch would wipe
    # previously enriched data (audit M1).
    for _field in (
        "locations",
        "country_codes",
        "countries",
        "location_lat",
        "location_lng",
        "location_radius_km",
        "location_geocode_label",
    ):
        _value = data.get(_field)
        if _value is not None:
            setattr(job, _field, _value)
    if data.get("remote") is not None:
        job.remote = bool(data.get("remote"))
    # Only overwrite work_mode when the refresh actually detected one — a source
    # that yields work_mode=None must not wipe a previously detected hybrid/remote
    # label (audit pass-2 P7; same class as M1).
    if data.get("work_mode") is not None:
        job.work_mode = data.get("work_mode")
    normalize._apply_if_present(job, "url", data.get("url"))
    # Keep the indexed canonical URL in sync so dedup stays fast (audit H7).
    new_canonical = normalize._canonical_job_url(data.get("url"))
    if new_canonical:
        job.canonical_url = new_canonical
    normalize._apply_if_present(job, "apply_url", data.get("apply_url") or data.get("url"))
    normalize._apply_if_present(job, "description", data.get("description"))
    normalize._apply_if_present(job, "source", data.get("source"))
    normalize._apply_if_present(job, "ats", data.get("ats"))
    normalize._apply_if_present(job, "ats_slug", data.get("ats_slug"))
    normalize._apply_if_present(job, "posted_at", data.get("posted_at"))
    # Keep the validated posting time in sync when a new posted_at is provided.
    # Relative phrases ("3 days ago") re-resolve against now on every refresh, so
    # a still-relative posting stays correctly aged.
    new_posted_ts, new_posted_date = normalize._parse_posting_time(data.get("posted_at"))
    if new_posted_date is not None:
        job.posted_date = new_posted_date
    if new_posted_ts is not None:
        job.posted_ts = new_posted_ts
    job.match_score = score
    job.score_breakdown = breakdown
    job.scored_at = datetime.now(timezone.utc) if score is not None else None
    job.last_seen_at = normalize._utcnow()
    job.source_status = "active"
    job.closed_at = None
    job.not_seen_count = 0
    job.fingerprint = fingerprint
    normalize._apply_if_present(job, "department", data.get("department"))
    normalize._apply_if_present(job, "employment_type", normalize._employment_type_for_job(data, experience_level))
    job.salary_min = data.get("salary_min")
    job.salary_max = data.get("salary_max")
    job.salary_currency = data.get("salary_currency")
    job.salary_period = data.get("salary_period")
    if data.get("tags") is not None:
        # Carry over startup tags from the incoming payload (existing behavior),
        # then layer in any new occupation:* tags inferred from the latest data
        # so jobs created before the taxonomy existed gain occupation tags on
        # the next refresh.
        merged = merge_startup_tags(job.tags, data.get("tags"))
        incoming_occupation_tags = [
            tag
            for tag in (data.get("tags") or [])
            if isinstance(tag, str) and tag.startswith(OCCUPATION_TAG_PREFIX)
        ]
        if incoming_occupation_tags:
            merged = merge_tags(merged, incoming_occupation_tags)
        job.tags = merged
    job.experience_level = experience_level
    job.experience_level_confidence = data.get("experience_level_confidence")
    job.metadata_provenance = data.get("metadata_provenance")


def _build_job(
    *,
    user_id: uuid.UUID,
    data: dict,
    score: float | None,
    breakdown: dict,
    fingerprint: str,
) -> Job:
    experience_level = data.get("experience_level") or normalize._experience_level_for_job(data)
    posted_ts, posted_date = normalize._parse_posting_time(data.get("posted_at"))
    return Job(
        user_id=user_id,
        external_id=data.get("external_id"),
        title=data.get("title", ""),
        company_name=data.get("company_name", "Unknown"),
        company_logo=data.get("company_logo"),
        location=data.get("location"),
        locations=data.get("locations"),
        country_codes=data.get("country_codes"),
        countries=data.get("countries"),
        location_lat=data.get("location_lat"),
        location_lng=data.get("location_lng"),
        location_radius_km=data.get("location_radius_km"),
        location_geocode_label=data.get("location_geocode_label"),
        remote=data.get("remote", False),
        work_mode=data.get("work_mode"),
        url=data.get("url"),
        canonical_url=normalize._canonical_job_url(data.get("url")),
        apply_url=data.get("apply_url") or data.get("url"),
        description=data.get("description"),
        employment_type=normalize._employment_type_for_job(data, experience_level),
        experience_level=experience_level,
        experience_level_confidence=data.get("experience_level_confidence"),
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        salary_currency=data.get("salary_currency"),
        salary_period=data.get("salary_period"),
        source=data.get("source", "unknown"),
        ats=data.get("ats"),
        ats_slug=data.get("ats_slug"),
        posted_at=normalize._coerce_posted_at(data.get("posted_at")),
        posted_date=posted_date,
        posted_ts=posted_ts,
        match_score=score,
        score_breakdown=breakdown,
        scored_at=datetime.now(timezone.utc) if score is not None else None,
        fingerprint=fingerprint,
        tags=data.get("tags"),
        metadata_provenance=data.get("metadata_provenance"),
        department=data.get("department"),
        source_status="active",
        last_seen_at=normalize._utcnow(),
        not_seen_count=0,
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
    source_key = normalize._job_source_key(source=source, ats=ats)

    with db.no_autoflush:
        if source_key and external_id:
            result = await db.execute(
                select(Job)
                .where(Job.user_id == user_id, Job.source == source_key, Job.external_id == external_id)
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            existing = normalize._result_first(result)
            if existing:
                return existing

        normalized_url = normalize._canonical_job_url(url)
        if normalized_url:
            # Indexed exact match on the stored canonical URL (audit H7) — replaces
            # the previous unbounded scan that loaded every job for the user+source
            # and recomputed canonical URLs in Python.
            result = await db.execute(
                select(Job)
                .where(Job.user_id == user_id, Job.canonical_url == normalized_url)
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            existing = normalize._result_first(result)
            if existing:
                return existing

            # Fallback for legacy rows ingested before canonical_url existed: scan
            # only rows that still lack it, narrowed by host, and backfill on match.
            host = urlparse(normalized_url).netloc
            legacy_filters = [
                Job.user_id == user_id,
                Job.url.is_not(None),
                Job.canonical_url.is_(None),
            ]
            if host:
                # Escape LIKE metacharacters so a host containing % or _ can't widen
                # the scan (audit pass-2 P14).
                safe_host = host.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                legacy_filters.append(Job.url.ilike(f"%{safe_host}%", escape="\\"))
            legacy_result = await db.execute(
                select(Job).where(*legacy_filters).order_by(Job.created_at.asc(), Job.id.asc())
            )
            for existing in legacy_result.scalars().all():
                if normalize._canonical_job_url(existing.url) == normalized_url:
                    existing.canonical_url = normalized_url
                    return existing

        if fingerprint:
            result = await db.execute(
                select(Job)
                .where(Job.user_id == user_id, Job.fingerprint == fingerprint)
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            existing = normalize._result_first(result)
            if existing:
                return existing

    return None


def _score_job(job_data: dict, profile: Profile | None) -> tuple[float | None, dict]:
    """Score a job against the user's profile using the enhanced scorer.

    Delegates to match_scoring.score_job for multi-axis algorithmic matching
    with skill synonyms, word-boundary matching, experience relevance, etc.

    Returns:
        (score 0-100, breakdown dict)
    """
    from app.services.match_scoring import score_job  # noqa: PLC0415
    return score_job(job_data, profile)


async def load_profile_for_scoring(
    db: AsyncSession, user_id: uuid.UUID
) -> Profile | None:
    """Load the user's profile for scoring, DETACHED from the session.

    ``score_job`` reads profile columns (``resume_parsed``, ``target_*``) from a
    *sync* function. If the session later rolls back — a job source fails mid
    ``discover_jobs`` and the handler calls ``db.rollback()`` — SQLAlchemy
    EXPIRES every attached ORM object. The next attribute read on the profile
    would then trigger a *synchronous* reload from inside the sync scorer,
    raising ``MissingGreenlet: greenlet_spawn has not been called``. Note
    ``expire_on_commit=False`` does NOT prevent this: rollback expires regardless.

    Detaching (``expunge``) the profile right after load makes its already-loaded
    columns immune to both commit- and rollback-driven expiry. Safe here because
    scoring only reads columns, never a lazy relationship (which would raise
    ``DetachedInstanceError`` on a detached object).
    """
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile is not None:
        db.expunge(profile)
    return profile


async def _record_source_runs(
    db: AsyncSession,
    *,
    refresh_run_id: uuid.UUID | None,
    source_stats: list[dict],
) -> None:
    if not refresh_run_id:
        return
    for stat in source_stats:
        db.add(
            JobSourceRun(
                refresh_run_id=refresh_run_id,
                source=stat["source"],
                status=stat.get("status") or "success",
                raw_count=int(stat.get("raw_count") or 0),
                new_count=int(stat.get("new_count") or 0),
                existing_count=int(stat.get("existing_count") or 0),
                duplicate_count=int(stat.get("duplicate_count") or 0),
                skipped_count=int(stat.get("skipped_count") or 0),
                error=stat.get("error"),
                details=stat.get("details"),
                started_at=stat["started_at"],
                finished_at=stat.get("finished_at"),
                duration_seconds=stat.get("duration_seconds"),
            )
        )


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


def _infer_occupation_tags_for_job(data: dict) -> None:
    """Stamp `occupation:<key>` tags on a raw job dict in-place.

    Honors any explicit occupation tags already present (e.g., from the
    newgrad-jobs scraper's source-category hint). Otherwise falls back to
    title/description classification, and finally to the occupation whose
    discover query surfaced the job (``_occupation_hint``), so query-seeded
    jobs with unclassifiable titles stay visible to occupation filters.
    """
    hint = data.pop("_occupation_hint", None)
    existing = data.get("tags") or []
    explicit_keys: list[str] = []
    for tag in existing:
        if isinstance(tag, str) and tag.startswith(OCCUPATION_TAG_PREFIX):
            explicit_keys.append(tag[len(OCCUPATION_TAG_PREFIX):])

    inferred = occupation_tags_for_job(
        title=data.get("title"),
        description=data.get("description"),
        explicit_keys=explicit_keys or None,
        fallback_keys=[hint] if isinstance(hint, str) and hint else None,
    )
    if inferred:
        data["tags"] = merge_tags(existing, inferred)


def recompute_occupation_tags(job: Job) -> list[str] | None:
    """Return a corrected tag list for a stored job, or ``None`` if unchanged.

    Re-derives `occupation:` tags purely from the job's title/description (no
    discover-hint fallback), so a stored job's occupation tags reflect what the
    role actually is. This drops stale fallback tags that mis-labeled a role (e.g.
    an engineering job tagged ``occupation:marketing`` because it was fetched
    during a marketing discover) and adds tags the classifier now recognizes.
    Non-occupation tags (skills, startup provenance) are preserved.
    """
    current = list(job.tags or [])
    non_occupation = [
        t for t in current
        if not (isinstance(t, str) and t.startswith(OCCUPATION_TAG_PREFIX))
    ]
    current_occupation = sorted(
        t for t in current
        if isinstance(t, str) and t.startswith(OCCUPATION_TAG_PREFIX)
    )
    fresh = occupation_tags_for_job(title=job.title, description=job.description)
    if sorted(fresh) == current_occupation:
        return None
    return non_occupation + fresh


async def _store_raw_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    raw_jobs: list[dict],
    profile: Profile | None,
) -> list[Job]:
    """Deduplicate and store raw job dicts from any source."""
    stored: list[Job] = []
    seen_job_keys: set[str] = set()
    refreshed_existing = False
    known_startup_companies = (
        await _load_known_startup_company_names(db, user_id) if raw_jobs else set()
    )

    for data in raw_jobs:
        _infer_startup_tags_for_job(data, known_startup_companies)
        _infer_occupation_tags_for_job(data)
        data = normalize_job_metadata(data)
        fp = normalize._fingerprint(data.get("company_name", ""), data.get("title", ""), data.get("location", ""))
        job_key = normalize._job_identity_key(data, fingerprint=fp)
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
        experience_level = normalize._experience_level_for_job(data)
        if existing:
            _refresh_existing_job(
                existing,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            refreshed_existing = True
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

    if stored or refreshed_existing:
        await db.commit()

    if stored:
        # Trigger auto-prospect for newly stored jobs (if enabled)
        try:
            await _maybe_auto_prospect(db, user_id, stored)
        except Exception:
            logger.debug("Auto-prospect trigger check failed", exc_info=True)
        # Pre-warm the contact cache for the top companies so "Find People"
        # feels instant on the jobs the user is most likely to open (default on).
        try:
            await _maybe_prewarm_people(db, user_id, stored)
        except Exception:
            logger.debug("People pre-warm trigger check failed", exc_info=True)

    return stored


async def mark_stale_jobs_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    stale_after_days: int = 14,
    closed_after_days: int = 45,
) -> dict:
    """Mark jobs that have not been seen recently as stale/closed.

    This avoids presenting old postings as confidently active while preserving
    user tracking state for jobs they may have saved or applied to.
    """
    now = normalize._utcnow()
    stale_cutoff = now - timedelta(days=stale_after_days)
    closed_cutoff = now - timedelta(days=closed_after_days)
    result = await db.execute(
        select(Job).where(
            Job.user_id == user_id,
            Job.last_seen_at.is_not(None),
            Job.last_seen_at < stale_cutoff,
            Job.source_status != "closed",
        )
    )
    stale_count = 0
    closed_count = 0
    for job in result.scalars().all():
        if job.last_seen_at and job.last_seen_at < closed_cutoff:
            job.source_status = "closed"
            job.closed_at = job.closed_at or now
            closed_count += 1
        else:
            job.source_status = "stale"
            stale_count += 1
        job.not_seen_count = (job.not_seen_count or 0) + 1

    if stale_count or closed_count:
        await db.commit()
    return {"stale": stale_count, "closed": closed_count}


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


async def _maybe_prewarm_people(
    db: AsyncSession,
    user_id: uuid.UUID,
    jobs: list,
) -> None:
    """Mark newly stored jobs ``pending`` and queue a per-job people pre-warm.

    On by default (opt-out via settings). Every new job is held out of the feed
    (``people_prewarm_status="pending"``) until its background search finds the
    top recruiter / hiring manager / next-best contact and saves a snapshot, so
    opening the job is instant. Highest-scored jobs warm first; a runaway batch
    is capped at ``PREWARM_MAX_JOBS_PER_BATCH`` (the tail stays visible without a
    pre-warm). Never finds emails, drafts, or sends — discovery only.
    """
    from app.tasks.auto_prospect import prewarm_job_people  # noqa: PLC0415
    from app.services.settings_service import is_people_prewarm_enabled  # noqa: PLC0415

    if not await is_people_prewarm_enabled(db, user_id):
        return  # leave jobs "ready" so they show immediately

    candidates = [job for job in jobs if getattr(job, "id", None) is not None]
    if not candidates:
        return

    candidates.sort(
        key=lambda j: getattr(j, "match_score", None) or 0.0, reverse=True
    )
    selected = candidates[:PREWARM_MAX_JOBS_PER_BATCH]
    if len(candidates) > len(selected):
        logger.warning(
            "People pre-warm batch capped: user=%s queued=%d skipped=%d",
            user_id, len(selected), len(candidates) - len(selected),
        )

    # Mark pending and COMMIT before enqueuing: otherwise a fast worker could
    # complete and set the job back to "ready" before this write lands, leaving
    # it stuck pending until the reveal timeout.
    for job in selected:
        job.people_prewarm_status = "pending"
    await db.commit()

    for job in selected:
        try:
            prewarm_job_people.delay(str(user_id), str(job.id))
        except Exception:
            logger.debug("Failed to queue job people pre-warm", exc_info=True)
            # Don't strand the job in "pending" forever if enqueue failed.
            job.people_prewarm_status = "ready"
    await db.commit()
