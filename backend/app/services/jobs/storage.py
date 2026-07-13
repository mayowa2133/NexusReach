"""Job persistence: build/find/refresh rows, scoring, tagging, raw-job storage, staleness."""

import logging
from sqlalchemy.exc import IntegrityError
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
from app.services.occupation_taxonomy import classify_title, occupation_tags_for_job
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy import tuple_
from sqlalchemy.orm import defer
from app.utils.startup_jobs import startup_source_tag
from datetime import timedelta
from datetime import timezone
from urllib.parse import urlparse
import uuid
from app.services.jobs import normalize


logger = logging.getLogger(__name__)

# Safety cap on people pre-warm jobs queued from one discovery batch.
# Every new job gets people pre-warmed, but a runaway run shouldn't queue
# thousands of tasks at once. Highest-scored jobs warm first; any tail beyond
# the cap stays visible without a pre-warm (Find People still works live).
PREWARM_MAX_JOBS_PER_BATCH = 300

# Max jobs per company-grouped pre-warm task: same-employer jobs share company
# resolution and cache hits, but one task must stay comfortably inside its
# time budget (auto_prospect.PREWARM_BATCH_TIME_BUDGET_SECONDS).
PREWARM_COMPANY_BATCH_MAX = 5


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


# Dedup lookups run once per imported job on every hourly board crawl and
# 15-min feed refresh, so at ~24k jobs/crawl they dominate Supabase egress
# (billed on bytes read out of Postgres). The heavy columns below are the bulk
# of each row — `description` alone is ~74% of the ~3.5 KB average width — and
# none are *read* when refreshing an existing row (`_refresh_existing_job` only
# overwrites them, and overwriting a deferred attribute issues no SELECT). The
# small read on this path (`tags`) is deliberately left loaded. Deferring these
# cuts the per-lookup read to the identity/dedup columns, dropping dedup egress
# by roughly 3-4x. Never read a deferred column from a returned row on the
# async session — that would trigger a lazy load and raise MissingGreenlet.
_DEDUP_DEFER_OPTIONS = (
    defer(Job.description),
    defer(Job.score_breakdown),
    defer(Job.metadata_provenance),
    defer(Job.locations),
    defer(Job.offer_details),
    defer(Job.interview_rounds),
)


# Batch size for the set-based dedup prefetch IN-queries. Large enough to keep
# a full board-crawl batch to a handful of round trips, small enough that the
# bind-parameter lists stay comfortable for Postgres.
_DEDUP_PREFETCH_CHUNK = 500


def _chunked(values: list, size: int = _DEDUP_PREFETCH_CHUNK):
    for start in range(0, len(values), size):
        yield values[start : start + size]


class _DedupIndex:
    """In-memory lookup of existing jobs, prefetched once per store batch.

    Mirrors the per-row probe order of ``_find_existing_job`` exactly:
    (source, external_id) → canonical_url → legacy canonical (backfilled on
    match) → fingerprint. Replaces up to 4 DB round trips *per raw job* with a
    handful of set-based IN queries per batch.
    """

    def __init__(self) -> None:
        self.by_source_external: dict[tuple[str, str], Job] = {}
        self.by_canonical: dict[str, Job] = {}
        self.legacy_by_canonical: dict[str, Job] = {}
        self.by_fingerprint: dict[str, Job] = {}

    def lookup(
        self,
        *,
        source_key: str | None,
        external_id: str | None,
        normalized_url: str | None,
        fingerprint: str | None,
    ) -> Job | None:
        if source_key and external_id:
            job = self.by_source_external.get((source_key, str(external_id)))
            if job is not None:
                return job
        if normalized_url:
            job = self.by_canonical.get(normalized_url)
            if job is not None:
                return job
            job = self.legacy_by_canonical.get(normalized_url)
            if job is not None:
                # Same backfill the per-row legacy scan performs on match.
                job.canonical_url = normalized_url
                return job
        if fingerprint:
            job = self.by_fingerprint.get(fingerprint)
            if job is not None:
                return job
        return None


async def _prefetch_existing_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    prepared: list[tuple[dict, str]],
) -> _DedupIndex:
    """Bulk-load every job that could dedup against this batch of raw rows.

    ``prepared`` holds ``(normalized_data, fingerprint)`` pairs. Keep-first
    semantics match the per-row queries' ``ORDER BY created_at, id``: rows for
    one key value always land in the same chunk, so ``setdefault`` over the
    ordered result preserves the earliest match.
    """
    index = _DedupIndex()
    pairs: set[tuple[str, str]] = set()
    urls: set[str] = set()
    fingerprints: set[str] = set()
    for data, fp in prepared:
        source_key = normalize._job_source_key(
            source=data.get("source"), ats=data.get("ats")
        )
        external_id = data.get("external_id")
        if source_key and external_id:
            pairs.add((source_key, str(external_id)))
        normalized_url = normalize._canonical_job_url(data.get("url"))
        if normalized_url:
            urls.add(normalized_url)
        if fp:
            fingerprints.add(fp)

    with db.no_autoflush:
        for chunk in _chunked(sorted(pairs)):
            result = await db.execute(
                select(Job)
                .options(*_DEDUP_DEFER_OPTIONS)
                .where(
                    Job.user_id == user_id,
                    tuple_(Job.source, Job.external_id).in_(chunk),
                )
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            for job in result.scalars().all():
                index.by_source_external.setdefault(
                    (job.source, job.external_id), job
                )

        for chunk in _chunked(sorted(urls)):
            result = await db.execute(
                select(Job)
                .options(*_DEDUP_DEFER_OPTIONS)
                .where(Job.user_id == user_id, Job.canonical_url.in_(chunk))
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            for job in result.scalars().all():
                if job.canonical_url:
                    index.by_canonical.setdefault(job.canonical_url, job)

        if urls:
            # Legacy rows ingested before canonical_url existed: canonicalize
            # once per batch instead of once per raw job (they backfill on
            # match, so this set only shrinks over time).
            result = await db.execute(
                select(Job)
                .options(*_DEDUP_DEFER_OPTIONS)
                .where(
                    Job.user_id == user_id,
                    Job.canonical_url.is_(None),
                    Job.url.is_not(None),
                )
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            for job in result.scalars().all():
                canonical = normalize._canonical_job_url(job.url)
                if canonical and canonical in urls:
                    index.legacy_by_canonical.setdefault(canonical, job)

        for chunk in _chunked(sorted(fingerprints)):
            result = await db.execute(
                select(Job)
                .options(*_DEDUP_DEFER_OPTIONS)
                .where(Job.user_id == user_id, Job.fingerprint.in_(chunk))
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            for job in result.scalars().all():
                if job.fingerprint:
                    index.by_fingerprint.setdefault(job.fingerprint, job)

    return index


async def _find_existing_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str | None,
    ats: str | None,
    external_id: str | None,
    url: str | None,
    fingerprint: str | None,
    index: _DedupIndex | None = None,
) -> Job | None:
    source_key = normalize._job_source_key(source=source, ats=ats)

    if index is not None:
        # Batch path: every candidate was prefetched set-based, so dedup is a
        # pure in-memory lookup (identical probe order to the queries below).
        return index.lookup(
            source_key=source_key,
            external_id=external_id,
            normalized_url=normalize._canonical_job_url(url),
            fingerprint=fingerprint,
        )

    with db.no_autoflush:
        if source_key and external_id:
            result = await db.execute(
                select(Job)
                .options(*_DEDUP_DEFER_OPTIONS)
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
                .options(*_DEDUP_DEFER_OPTIONS)
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
                select(Job)
                .options(*_DEDUP_DEFER_OPTIONS)
                .where(*legacy_filters)
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            for existing in legacy_result.scalars().all():
                if normalize._canonical_job_url(existing.url) == normalized_url:
                    existing.canonical_url = normalized_url
                    return existing

        if fingerprint:
            result = await db.execute(
                select(Job)
                .options(*_DEDUP_DEFER_OPTIONS)
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


def classify_source_health(
    rows: list[dict],
    *,
    min_attempts: int,
    failure_rate_threshold: float,
) -> list[dict]:
    """Flag sources whose recent run history looks like a sustained outage.

    Pure function over aggregated per-source rows (``source``, ``attempts``,
    ``failures``, ``last_success``, ``sample_error``) so it's unit-testable
    without a database. A source is ``degraded`` only when it has enough signal
    (``attempts >= min_attempts``) *and* is failing at or above
    ``failure_rate_threshold`` — so a lone transient failure never trips it.
    """
    results: list[dict] = []
    for row in rows:
        attempts = int(row.get("attempts") or 0)
        failures = int(row.get("failures") or 0)
        rate = (failures / attempts) if attempts else 0.0
        degraded = attempts >= min_attempts and rate >= failure_rate_threshold
        results.append(
            {
                "source": row.get("source"),
                "attempts": attempts,
                "failures": failures,
                "failure_rate": round(rate, 4),
                "last_success": row.get("last_success"),
                "sample_error": row.get("sample_error"),
                "degraded": degraded,
            }
        )
    return results


async def evaluate_source_health(
    db: AsyncSession,
    *,
    window_hours: int,
    min_attempts: int,
    failure_rate_threshold: float,
) -> list[dict]:
    """Aggregate JobSourceRun outcomes per source over a recent window.

    Returns the classification produced by ``classify_source_health``. The
    aggregation runs in SQL (counts + FILTERed counts) so we never load the
    per-run rows into memory.
    """
    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    is_failed = JobSourceRun.status == "failed"
    is_success = JobSourceRun.status == "success"
    stmt = (
        select(
            JobSourceRun.source,
            sa_func.count().label("attempts"),
            sa_func.count().filter(is_failed).label("failures"),
            sa_func.max(JobSourceRun.created_at).filter(is_success).label("last_success"),
            sa_func.max(JobSourceRun.error).filter(is_failed).label("sample_error"),
        )
        .where(JobSourceRun.created_at >= window_start)
        .group_by(JobSourceRun.source)
        .order_by(JobSourceRun.source)
    )
    rows = (await db.execute(stmt)).all()
    mapped = [
        {
            "source": row.source,
            "attempts": row.attempts,
            "failures": row.failures,
            "last_success": row.last_success.isoformat() if row.last_success else None,
            "sample_error": row.sample_error,
        }
        for row in rows
    ]
    return classify_source_health(
        mapped,
        min_attempts=min_attempts,
        failure_rate_threshold=failure_rate_threshold,
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

    title_keys = classify_title(data.get("title"))
    content_keys = title_keys or classify_title(
        data.get("title"), data.get("description")
    )

    inferred = occupation_tags_for_job(
        title=data.get("title"),
        description=data.get("description"),
        explicit_keys=explicit_keys or None,
        fallback_keys=[hint] if isinstance(hint, str) and hint else None,
    )
    if inferred:
        data["tags"] = merge_tags(existing, inferred)
        if explicit_keys:
            source, confidence = "explicit_source_tag", 1.0
        elif title_keys:
            source, confidence = "title_classifier", 0.95
        elif content_keys:
            source, confidence = "description_classifier", 0.75
        else:
            source, confidence = "query_hint", 0.25
        provenance = (
            dict(data.get("metadata_provenance"))
            if isinstance(data.get("metadata_provenance"), dict)
            else {}
        )
        provenance["occupation_classification"] = {
            "version": 1,
            "keys": [tag[len(OCCUPATION_TAG_PREFIX):] for tag in inferred],
            "source": source,
            "confidence": confidence,
            "query_hint": hint if isinstance(hint, str) else None,
        }
        data["metadata_provenance"] = provenance


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

    # Normalize the whole batch first so dedup candidates can be prefetched
    # with a handful of set-based queries instead of up to 4 round trips per
    # raw job (the board crawl stores ~24k rows per run).
    prepared: list[tuple[dict, str]] = []
    for data in raw_jobs:
        _infer_startup_tags_for_job(data, known_startup_companies)
        _infer_occupation_tags_for_job(data)
        data = normalize_job_metadata(data)
        fp = normalize._fingerprint(data.get("company_name", ""), data.get("title", ""), data.get("location", ""))
        job_key = normalize._job_identity_key(data, fingerprint=fp)
        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)
        prepared.append((data, fp))

    # Resolve + commit with one retry: concurrent discovery tasks for the same
    # user can insert a row for the same (user_id, ats, external_id) between our
    # prefetch and our commit, so the commit raises IntegrityError on the unique
    # constraint (Sentry PYTHON-1B, exposed once the worker went to concurrency
    # 2). On conflict we roll back and redo the resolve loop — the re-prefetch
    # now sees the row the other task inserted, so the conflict becomes a
    # refresh instead of a duplicate insert.
    for attempt in range(2):
        stored = []
        refreshed_existing = False
        dedup_index = (
            await _prefetch_existing_jobs(db, user_id, prepared) if prepared else None
        )

        for data, fp in prepared:
            existing = await _find_existing_job(
                db,
                user_id=user_id,
                source=data.get("source"),
                ats=data.get("ats"),
                external_id=data.get("external_id"),
                url=data.get("url"),
                fingerprint=fp,
                index=dedup_index,
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

        if not (stored or refreshed_existing):
            break
        try:
            await db.commit()
            break
        except IntegrityError:
            await db.rollback()
            if attempt == 1:
                # A second concurrent insert hit the same tiny window; the data
                # is safe (the constraint held), and the next refresh cycle will
                # pick up these rows. Drop this batch rather than error out.
                logger.warning(
                    "Job store still conflicting after retry for user %s; "
                    "skipping batch of %d",
                    user_id,
                    len(prepared),
                )
                return []

    if stored:
        await finalize_new_jobs(db, user_id, stored)

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

    Jobs are queued as company-grouped batches (``prewarm_job_people_batch``):
    same-employer jobs share company resolution and cache hits, and one task
    per company group avoids per-task overhead (fresh NullPool DB connection,
    child recycling) across a 300-job fan-out.
    """
    from app.tasks.auto_prospect import prewarm_job_people_batch  # noqa: PLC0415
    from app.services.settings_service import is_people_prewarm_enabled  # noqa: PLC0415
    from app.utils.company_identity import normalize_company_name  # noqa: PLC0415

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

    # Group by normalized company, preserving the score order of each group's
    # best job, then chunk so no single task exceeds its time budget.
    groups: dict[str, list] = {}
    group_order: list[str] = []
    for job in selected:
        company_key = (
            normalize_company_name(getattr(job, "company_name", "") or "")
            or f"__unknown__{job.id}"
        )
        if company_key not in groups:
            groups[company_key] = []
            group_order.append(company_key)
        groups[company_key].append(job)

    batches: list[list] = []
    for company_key in group_order:
        group = groups[company_key]
        for start in range(0, len(group), PREWARM_COMPANY_BATCH_MAX):
            batches.append(group[start : start + PREWARM_COMPANY_BATCH_MAX])

    # Mark pending and COMMIT before enqueuing: otherwise a fast worker could
    # complete and set the job back to "ready" before this write lands, leaving
    # it stuck pending until the reveal timeout.
    for job in selected:
        job.people_prewarm_status = "pending"
    await db.commit()

    for batch in batches:
        try:
            prewarm_job_people_batch.delay(
                str(user_id), [str(job.id) for job in batch]
            )
        except Exception:
            logger.debug("Failed to queue job people pre-warm", exc_info=True)
            # Don't strand the jobs in "pending" forever if enqueue failed.
            for job in batch:
                job.people_prewarm_status = "ready"
    await db.commit()


async def finalize_new_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    jobs: list[Job],
) -> None:
    """Apply post-insert policies consistently across every discovery source."""
    if not jobs:
        return
    try:
        await _maybe_auto_prospect(db, user_id, jobs)
    except Exception:
        logger.debug("Auto-prospect trigger check failed", exc_info=True)
    try:
        await _maybe_prewarm_people(db, user_id, jobs)
    except Exception:
        logger.debug("People pre-warm trigger check failed", exc_info=True)
