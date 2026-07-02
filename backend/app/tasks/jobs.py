"""Celery tasks for automatic job feed refresh and notifications."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from app.tasks import celery_app, run_async
from app.clients import usajobs_client, workday_client
from app.database import async_session
from app.models.notification import Notification
from app.models.search_preference import SearchPreference
from app.models.company import Company
from app.models.job_refresh_run import JobRefreshRun
from app.services.job_service import (
    fetch_curated_ats_source_payloads,
    mark_stale_jobs_for_user,
    run_startup_refresh_for_query,
    search_jobs,
    store_curated_ats_payloads_for_user,
    summarize_source_stats,
)
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


def _is_missing_search_preferences_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return 'relation "search_preferences" does not exist' in message


async def _notification_exists(
    db,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    type: str,
) -> bool:
    """Check whether a notification already exists for a job + type."""
    stmt = (
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.job_id == job_id,
            Notification.type == type,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


# Crash backstop for the per-user refresh lock: long enough for a slow full
# refresh, short enough that a worker OOM/SIGKILL can't block a user's
# refreshes for more than one beat cycle.
FEED_REFRESH_LOCK_TTL_SECONDS = 1800


async def _refresh_user_feeds(user_id: uuid.UUID) -> int:
    """Re-run all enabled search preferences for a user and create notifications.

    Isolation notes (Sentry PYTHON-Z / PYTHON-16):
    - A per-user Redis lock skips the run when another refresh for the same
      user is already in flight — the hourly all-users beat and the
      ensure-fresh nudge can overlap now that the worker runs two slots, which
      caused lock contention and statement timeouts on the same pref rows.
    - Each preference refreshes in its OWN session/connection
      (``_refresh_single_preference``), so one preference's poisoned
      connection (statement timeout mid-flush, cancelled commit) can't sink
      the user's remaining preferences.
    """
    from app.clients import search_cache_client  # noqa: PLC0415

    lock_key = f"feed_refresh_lock:{user_id}"
    if not await search_cache_client.acquire_lock(
        lock_key, ttl_seconds=FEED_REFRESH_LOCK_TTL_SECONDS
    ):
        logger.info("Feed refresh already in flight for user %s; skipping", user_id)
        return 0

    try:
        async with async_session() as db:
            # Fetch enabled search preferences; detach plain ids — each
            # preference reloads inside its own session.
            stmt = select(SearchPreference).where(
                SearchPreference.user_id == user_id,
                SearchPreference.enabled == True,  # noqa: E712
            )
            result = await db.execute(stmt)
            pref_ids = [pref.id for pref in result.scalars().all()]

            if not pref_ids:
                return 0

            # Fetch starred companies for this user
            starred_stmt = select(Company).where(
                Company.user_id == user_id,
                Company.starred == True,  # noqa: E712
            )
            starred_result = await db.execute(starred_stmt)
            starred_companies = {
                c.name.lower().strip() for c in starred_result.scalars().all()
            }

        total_new = 0
        for pref_id in pref_ids:
            total_new += await _refresh_single_preference(
                user_id, pref_id, starred_companies
            )

        async with async_session() as db:
            await mark_stale_jobs_for_user(db, user_id)

        return total_new
    finally:
        await search_cache_client.release_lock(lock_key)


async def _refresh_single_preference(
    user_id: uuid.UUID,
    pref_id: uuid.UUID,
    starred_companies: set[str],
) -> int:
    """Refresh one saved search in its own session; returns the new-job count."""
    async with async_session() as db:
        pref = await db.get(SearchPreference, pref_id)
        if pref is None or not pref.enabled:
            return 0

        # Plain-value copies for the except handler: rollback expires ORM
        # attributes, and reading an expired attribute from except-path code
        # lazy-loads synchronously and raises MissingGreenlet (Sentry PYTHON-Z).
        query_text = pref.query
        pref_location = pref.location
        pref_remote_only = bool(pref.remote_only)
        pref_mode = getattr(pref, "mode", "default") or "default"

        started_at = datetime.now(timezone.utc)
        refresh_run = JobRefreshRun(
            id=uuid.uuid4(),
            user_id=user_id,
            search_preference_id=pref_id,
            mode=pref_mode,
            query=query_text,
            location=pref_location,
            remote_only=pref_remote_only,
            status="running",
            started_at=started_at,
        )
        db.add(refresh_run)
        pref.last_attempted_at = started_at
        await db.flush()
        source_stats: list[dict] = []
        try:
            if pref_mode == "startup":
                matched_jobs = await run_startup_refresh_for_query(
                    db=db,
                    user_id=user_id,
                    query=query_text,
                )
            else:
                matched_jobs = await search_jobs(
                    db=db,
                    user_id=user_id,
                    query=query_text,
                    location=pref_location,
                    remote_only=pref_remote_only,
                    limit=50,
                    refresh_run_id=refresh_run.id,
                    source_stats=source_stats,
                )

            # search_jobs now also returns refreshed existing rows (audit C3);
            # keep counts and notifications scoped to genuinely-new jobs. The
            # startup path returns only new rows, so absence of the flag = new.
            new_jobs = [
                job
                for job in matched_jobs
                if getattr(job, "_is_new_job", True)
            ]

            # Record refresh metadata
            finished_at = datetime.now(timezone.utc)
            summary = summarize_source_stats(source_stats)
            refresh_run.finished_at = finished_at
            refresh_run.duration_seconds = round(
                (finished_at - started_at).total_seconds(), 3
            )
            refresh_run.total_new = len(new_jobs)
            refresh_run.total_seen = summary["total_seen"]
            refresh_run.total_existing = summary["total_existing"]
            refresh_run.total_duplicates = summary["total_duplicates"]
            refresh_run.total_errors = summary["total_errors"]
            refresh_run.status = (
                "partial_success" if summary["total_errors"] else "success"
            )
            pref.last_refreshed_at = finished_at
            pref.last_success_at = finished_at
            pref.last_duration_seconds = refresh_run.duration_seconds
            pref.last_error = (
                f"{summary['total_errors']} source(s) failed"
                if summary["total_errors"]
                else None
            )
            pref.new_jobs_found = len(new_jobs)
            await db.commit()

            for job in new_jobs:
                company_lower = job.company_name.lower().strip()

                # Check if this job is from a starred company
                if company_lower in starred_companies:
                    if not await _notification_exists(
                        db, user_id=user_id, job_id=job.id, type="starred_company_job",
                    ):
                        await create_notification(
                            db,
                            user_id,
                            type="starred_company_job",
                            title=f"{job.company_name} posted: {job.title}",
                            body=f"Your starred company has a new opening in {job.location or 'Unknown location'}",
                            job_id=job.id,
                        )
                elif job.match_score is not None and job.match_score >= 50:
                    if not await _notification_exists(
                        db, user_id=user_id, job_id=job.id, type="new_job",
                    ):
                        await create_notification(
                            db,
                            user_id,
                            type="new_job",
                            title=f"New match: {job.title} at {job.company_name}",
                            body=f"{int(job.match_score)}% match score",
                            job_id=job.id,
                        )

            return len(new_jobs)

        except Exception:
            # Log FIRST with plain-value context — the metadata write below can
            # itself fail on a poisoned connection and must not eat this.
            logger.exception(
                "Failed to refresh feed for user %s, query '%s'",
                user_id,
                query_text,
            )
            try:
                # search_jobs / startup refresh can leave the transaction in a
                # failed state (for example on statement timeout during flush).
                # Roll back before writing failure metadata or the follow-up
                # commit itself raises PendingRollbackError.
                await db.rollback()
                finished_at = datetime.now(timezone.utc)
                db.add(refresh_run)
                refresh_run.finished_at = finished_at
                refresh_run.duration_seconds = round(
                    (finished_at - started_at).total_seconds(), 3
                )
                refresh_run.status = "failed"
                refresh_run.error = "Refresh failed; see worker logs for traceback."
                pref.last_attempted_at = started_at
                pref.last_duration_seconds = refresh_run.duration_seconds
                pref.last_error = refresh_run.error
                await db.commit()
            except Exception:
                # The connection itself is poisoned (e.g. cancelled mid-commit).
                # Give up on metadata for this cycle: this session closes here,
                # the next preference opens a fresh connection, and the next
                # refresh cycle overwrites this metadata anyway.
                logger.warning(
                    "Could not record refresh failure metadata for pref %s", pref_id,
                )
            return 0


async def refresh_user_feeds(user_id: uuid.UUID) -> int:
    """Public wrapper for refreshing a single user's feeds. Returns new job count."""
    count = await _refresh_user_feeds(user_id)
    return count


@celery_app.task(
    name="app.tasks.jobs.refresh_single_user_feeds",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=300,
    max_retries=2,
)
def refresh_single_user_feeds(user_id: str) -> dict:
    """Celery task: light refresh of one user's saved searches (warm-feed nudge).

    Backs the debounced ``ensure-fresh`` nudge when a user opens the Jobs page
    and their feed already has jobs but has gone slightly stale. Cheap — runs the
    per-saved-search aggregator/Muse pass only, not the curated-board crawl
    (which the hourly global task already handles).
    """
    count = run_async(_refresh_user_feeds(uuid.UUID(user_id)))
    return {"status": "ok", "new_jobs": count}


async def _discover_for_user(user_id: uuid.UUID) -> int:
    """Run a full default + startup discovery pass for one user.

    This is the cold-start fill: it populates a user's feed immediately when they
    first set their targeting (so they never wait for the next background beat)
    and backs the empty-feed branch of the ``ensure-fresh`` nudge. Startup
    discovery is folded in (fail-soft) so startup roles surface in the same
    ambient feed instead of behind a separate button.
    """
    from app.services.jobs import discovery  # noqa: PLC0415

    total = 0
    async with async_session() as db:
        try:
            total += await discovery.discover_jobs(db, user_id, mode="default")
        except Exception:
            await db.rollback()
            logger.exception("cold-start default discover failed for user %s", user_id)
    # Startup is best-effort (Wellfound can 403); never let it sink the default fill.
    async with async_session() as db:
        try:
            total += await discovery.discover_jobs(db, user_id, mode="startup")
        except Exception:
            await db.rollback()
            logger.exception("cold-start startup discover failed for user %s", user_id)
    return total


@celery_app.task(
    name="app.tasks.jobs.discover_for_user",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=300,
    max_retries=2,
)
def discover_for_user(user_id: str) -> dict:
    """Celery task: full discovery pass for one user (cold-start / empty-feed fill)."""
    count = run_async(_discover_for_user(uuid.UUID(user_id)))
    return {"status": "ok", "new_jobs": count}


async def _discover_occupations_for_user(
    user_id: uuid.UUID, occupations: list[str]
) -> int:
    """Run discovery for an explicit set of occupations (chip-driven).

    Powers the Jobs-page occupation chips: selecting "Marketing" should *fetch*
    marketing roles (early-career boost included via the themuse source), not
    just filter the existing SWE-heavy feed. Occupation-routed discovery covers
    every category, so this works for tech and non-tech alike.
    """
    from app.services.jobs import discovery  # noqa: PLC0415

    async with async_session() as db:
        try:
            return await discovery.discover_jobs(db, user_id, occupations=occupations)
        except Exception:
            await db.rollback()
            logger.exception(
                "occupation discover failed for user %s (%s)", user_id, occupations
            )
            return 0


@celery_app.task(
    name="app.tasks.jobs.discover_occupations_for_user",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=300,
    max_retries=2,
)
def discover_occupations_for_user(user_id: str, occupations: list[str]) -> dict:
    """Celery task: discover an explicit occupation set for one user."""
    count = run_async(_discover_occupations_for_user(uuid.UUID(user_id), occupations))
    return {"status": "ok", "new_jobs": count}


async def _refresh_all() -> None:
    """Refresh job feeds for all users with enabled search preferences."""
    async with async_session() as db:
        try:
            stmt = (
                select(SearchPreference.user_id)
                .where(SearchPreference.enabled == True)  # noqa: E712
                .distinct()
            )
            result = await db.execute(stmt)
            user_ids = [row[0] for row in result.all()]
        except ProgrammingError as exc:
            if not _is_missing_search_preferences_table_error(exc):
                raise
            await db.rollback()
            logger.warning(
                "Skipping refresh_all_job_feeds because the search_preferences table is unavailable. "
                "Database migrations may not be applied yet."
            )
            return

    logger.info("Refreshing job feeds for %d users", len(user_ids))

    semaphore = asyncio.Semaphore(5)

    async def refresh_one(uid: uuid.UUID) -> None:
        async with semaphore:
            try:
                await _refresh_user_feeds(uid)
            except Exception:
                logger.exception("Failed to refresh feeds for user %s", uid)

    await asyncio.gather(*(refresh_one(uid) for uid in user_ids))


@celery_app.task(
    name="app.tasks.jobs.refresh_all_job_feeds",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def refresh_all_job_feeds() -> dict:
    """Celery task: refresh job feeds for all users with saved searches."""
    run_async(_refresh_all())
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auto-discover ATS boards (Greenhouse, Ashby, Lever, Workday)
# ---------------------------------------------------------------------------

async def _discover_all_boards() -> None:
    """Run ATS board discovery for every user with at least one saved search."""
    async with async_session() as db:
        try:
            prefs_stmt = (
                select(SearchPreference)
                .where(SearchPreference.enabled == True)  # noqa: E712
            )
            result = await db.execute(prefs_stmt)
            preferences = list(result.scalars().all())
        except ProgrammingError as exc:
            if not _is_missing_search_preferences_table_error(exc):
                raise
            await db.rollback()
            logger.warning(
                "Skipping discover_ats_boards because the search_preferences table is unavailable. "
                "Database migrations may not be applied yet."
            )
            return

    prefs_by_user: dict[uuid.UUID, list[SearchPreference]] = {}
    for pref in preferences:
        prefs_by_user.setdefault(pref.user_id, []).append(pref)
    user_ids = list(prefs_by_user)

    logger.info("Running ATS board auto-discovery for %d users", len(user_ids))
    source_payloads, source_stats = await fetch_curated_ats_source_payloads()

    # Curated non-tech employers (health systems, universities, banks/insurers,
    # retailers). Fetch every vertical here and let per-user saved-search
    # matching decide relevance downstream — so a nurse's "registered nurse"
    # search lands Sentara/Trinity jobs on refresh, the way a dev's search lands
    # Stripe/OpenAI. Folded into the existing workday:curated source bucket so
    # provenance and stats stay consistent (stored jobs map back to it).
    try:
        nontech_jobs = await workday_client.discover_all_nontech_workday(
            limit_per_company=40
        )
        if nontech_jobs:
            source_payloads.setdefault("workday:curated", []).extend(nontech_jobs)
            logger.info("Refresh: +%d curated non-tech workday jobs", len(nontech_jobs))
    except Exception:
        logger.exception("non-tech workday fetch failed in refresh")

    # Federal government postings (USAJobs). On-demand discover already routes
    # government seekers here; this gives the background refresh the same
    # coverage so a saved "Policy Analyst" search stays fresh, the way nurses get
    # Sentara. No-op (returns []) unless USAJobs is configured.
    try:
        from app.services.occupation_taxonomy import occupations_for_keys  # noqa: PLC0415

        gov_occ = occupations_for_keys(["public_sector_government"])
        gov_queries = list(gov_occ[0].default_search_queries) if gov_occ else []
        gov_jobs = await usajobs_client.discover_usajobs(gov_queries, limit_per_query=25)
        if gov_jobs:
            source_payloads.setdefault("usajobs", []).extend(gov_jobs)
            logger.info("Refresh: +%d USAJobs federal jobs", len(gov_jobs))
    except Exception:
        logger.exception("USAJobs fetch failed in refresh")

    for uid in user_ids:
        try:
            async with async_session() as db:
                started_at = datetime.now(timezone.utc)
                refresh_run = JobRefreshRun(
                    id=uuid.uuid4(),
                    user_id=uid,
                    search_preference_id=None,
                    mode="ats_discovery",
                    query="curated_ats_boards",
                    location=None,
                    remote_only=False,
                    status="running",
                    started_at=started_at,
                )
                db.add(refresh_run)
                await db.flush()
                new_count = await store_curated_ats_payloads_for_user(
                    db,
                    uid,
                    source_payloads=source_payloads,
                    source_stats=source_stats,
                    preferences=prefs_by_user.get(uid, []),
                    refresh_run_id=refresh_run.id,
                )
                # ~900 auto-discovered boards, crawled in memory-bounded chunks so
                # the worker can't OOM (holding them all at once SIGKILL'd it).
                from app.services.jobs import curated_boards as _cb  # noqa: PLC0415
                new_count += await _cb.crawl_and_store_discovered_boards(
                    db,
                    uid,
                    preferences=prefs_by_user.get(uid, []),
                    refresh_run_id=refresh_run.id,
                )
                finished_at = datetime.now(timezone.utc)
                refresh_run.finished_at = finished_at
                refresh_run.duration_seconds = round(
                    (finished_at - started_at).total_seconds(), 3
                )
                refresh_run.total_new = new_count
                refresh_run.status = "success"
                await mark_stale_jobs_for_user(db, uid)
                await db.commit()
                logger.info(
                    "ATS auto-discover: %d new jobs for user %s", new_count, uid,
                )
        except Exception:
            logger.exception("ATS auto-discover failed for user %s", uid)


@celery_app.task(
    name="app.tasks.jobs.discover_ats_boards",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def discover_ats_boards() -> dict:
    """Celery task: poll all curated ATS boards for new postings."""
    run_async(_discover_all_boards())
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Curated board health check (Workday config drift detection)
# ---------------------------------------------------------------------------

async def _verify_curated_boards() -> dict:
    """Probe every curated Workday config and log drift.

    Workday tenants migrate tiers/sites and a drifted config silently returns
    nothing. This surfaces the drift: WARNING-logs configs whose configured
    tier is dead (with the working replacement when auto-repair finds one, or
    as fully dead). Run scripts/verify_workday_boards.py to apply the fix.
    """
    results = await workday_client.verify_all_workday(repair=True)
    repaired = [r for r in results if r["status"] == "repaired"]
    dead = [r for r in results if r["status"] == "dead"]

    for r in repaired:
        logger.warning(
            "Workday board DRIFTED: %s tier %s dead, works on %s "
            "(update workday_client: company=%s site=%s wd=%s)",
            r["label"], r["old_wd"], r["wd"], r["company"], r["site"], r["wd"],
        )
    for r in dead:
        logger.warning(
            "Workday board DEAD: %s (%s/%s/%s) returns no jobs on any tier "
            "— rediscover site or remove",
            r["label"], r["company"], r["wd"], r["site"],
        )
    summary = {
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "repairable": len(repaired),
        "dead": len(dead),
    }
    logger.info("Curated board health check: %s", summary)
    return summary


@celery_app.task(
    name="app.tasks.jobs.verify_curated_boards",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=2,
)
def verify_curated_boards() -> dict:
    """Celery task: weekly health check for curated Workday config drift."""
    return run_async(_verify_curated_boards())


async def _monitor_source_health() -> dict:
    """Escalate *sustained* per-source outages to a single aggregated alert.

    Transient fetch failures are logged at WARNING by the fetch layer and never
    reach Sentry (a third-party board blipping for one cycle is expected). This
    reads the JobSourceRun history instead and, for any source failing across
    most of its attempts over the window, emits ONE ERROR per down source — so
    Sentry shows a single deduped issue ("Job source DOWN: dice …") with a
    rising count, the actionable "a source is actually broken" signal, rather
    than one event per timeout.
    """
    from app.services.jobs import constants, storage  # noqa: PLC0415

    async with async_session() as db:
        results = await storage.evaluate_source_health(
            db,
            window_hours=constants.SOURCE_HEALTH_WINDOW_HOURS,
            min_attempts=constants.SOURCE_HEALTH_MIN_ATTEMPTS,
            failure_rate_threshold=constants.SOURCE_HEALTH_FAILURE_RATE,
        )

    degraded = [r for r in results if r["degraded"]]
    for r in degraded:
        logger.error(
            "Job source DOWN: '%s' failed %d/%d (%.0f%%) over the last %dh "
            "(last success: %s). Sample error: %s",
            r["source"],
            r["failures"],
            r["attempts"],
            r["failure_rate"] * 100,
            constants.SOURCE_HEALTH_WINDOW_HOURS,
            r["last_success"] or "none in window",
            (r["sample_error"] or "n/a")[:300],
        )
    logger.info(
        "Source health check: %d sources evaluated, %d degraded%s",
        len(results),
        len(degraded),
        f" ({', '.join(str(r['source']) for r in degraded)})" if degraded else "",
    )
    return {"checked": len(results), "degraded": [r["source"] for r in degraded]}


@celery_app.task(
    name="app.tasks.jobs.monitor_source_health",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=2,
)
def monitor_source_health() -> dict:
    """Celery task: hourly per-source sustained-outage check (see _monitor_source_health)."""
    return run_async(_monitor_source_health())


async def _retag_occupation_tags(batch_size: int = 1000) -> dict:
    """Recompute `occupation:` tags on stored jobs from their title/description.

    Self-heals the existing feed after a classifier/routing change: drops stale
    discover-hint tags that mis-labeled roles (engineering jobs under Marketing)
    and adds occupation tags the classifier now recognizes. Keyset-paginated and
    expunged per batch so a full-table scan stays memory-bounded.
    """
    from app.models.job import Job  # noqa: PLC0415
    from app.services.jobs import storage  # noqa: PLC0415

    scanned = 0
    updated = 0
    last_id: uuid.UUID | None = None
    async with async_session() as db:
        while True:
            query = select(Job).order_by(Job.id).limit(batch_size)
            if last_id is not None:
                query = query.where(Job.id > last_id)
            rows = (await db.execute(query)).scalars().all()
            if not rows:
                break
            for job in rows:
                last_id = job.id
                scanned += 1
                fresh = storage.recompute_occupation_tags(job)
                if fresh is not None:
                    job.tags = fresh
                    updated += 1
            await db.commit()
            db.expunge_all()
    logger.info("retag_occupation_tags: scanned=%d updated=%d", scanned, updated)
    return {"scanned": scanned, "updated": updated}


@celery_app.task(
    name="app.tasks.jobs.retag_occupation_tags",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=2,
)
def retag_occupation_tags() -> dict:
    """Celery task: daily re-classification of stored jobs' occupation tags."""
    return run_async(_retag_occupation_tags())


# --- Re-scoring ---


async def _rescore_user_jobs(user_id: uuid.UUID) -> dict:
    """Re-score all jobs for a user against their current resume/profile.

    Only re-scores jobs that haven't been scored since the profile was last
    updated, or that have never been scored.
    """
    from app.models.job import Job  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415
    from app.services.match_scoring import score_job  # noqa: PLC0415

    stats = {"rescored": 0, "skipped": 0, "errors": 0}

    async with async_session() as db:
        # Load profile
        result = await db.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile or not profile.resume_parsed:
            return stats

        profile_updated = profile.updated_at

        # Get jobs needing re-scoring: scored_at is null OR scored_at < profile.updated_at
        result = await db.execute(
            select(Job).where(
                Job.user_id == user_id,
                Job.description.isnot(None),
            )
        )
        jobs = list(result.scalars().all())

        batch_count = 0
        for job in jobs:
            # Skip if already scored after profile was last updated
            if (
                job.scored_at is not None
                and profile_updated is not None
                and job.scored_at >= profile_updated
            ):
                stats["skipped"] += 1
                continue

            try:
                job_data = {
                    "title": job.title,
                    "company_name": job.company_name,
                    "location": job.location,
                    "description": job.description,
                    "remote": job.remote,
                    "experience_level": job.experience_level,
                }
                new_score, new_breakdown = score_job(job_data, profile)
                job.match_score = new_score
                job.score_breakdown = new_breakdown
                job.scored_at = datetime.now(timezone.utc)
                stats["rescored"] += 1
                batch_count += 1

                # Flush every 50 to avoid holding too much in memory
                if batch_count >= 50:
                    await db.flush()
                    batch_count = 0
            except Exception:
                stats["errors"] += 1
                logger.debug(
                    "Re-score failed: job=%s", job.id, exc_info=True,
                )

        await db.commit()

        if stats["rescored"] > 0:
            await create_notification(
                db,
                user_id,
                type="rescore_complete",
                title="Match scores updated",
                body=f"Re-scored {stats['rescored']} jobs against your updated resume.",
            )

    return stats


@celery_app.task(
    name="app.tasks.jobs.rescore_user_jobs",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=180,
    time_limit=240,
)
def rescore_user_jobs(user_id: str) -> dict:
    """Celery task: re-score all jobs for a user after resume/profile update."""
    return run_async(_rescore_user_jobs(uuid.UUID(user_id)))


async def _repair_job_apply_urls(user_id: uuid.UUID, job_ids: list[uuid.UUID]) -> int:
    """Resolve real apply URLs for the queued dice/newgrad rows.

    Runs the same capped repair that used to execute inline on the feed read
    (``search._repair_missing_apply_urls``), now off the request path.
    """
    from app.models.job import Job  # noqa: PLC0415
    from app.services.jobs import search as search_mod  # noqa: PLC0415

    if not job_ids:
        return 0
    async with async_session() as db:
        result = await db.execute(
            select(Job).where(Job.user_id == user_id, Job.id.in_(job_ids))
        )
        jobs = list(result.scalars().all())
        if not jobs:
            return 0
        await search_mod._repair_missing_apply_urls(db, jobs)
        return len(jobs)


@celery_app.task(
    name="app.tasks.jobs.repair_job_apply_urls",
    soft_time_limit=120,
    time_limit=180,
)
def repair_job_apply_urls(user_id: str, job_ids: list[str]) -> int:
    """Celery task: background apply-URL repair queued from the jobs feed read.

    No retries: the feed re-queues (debounced) on the next read if rows are
    still missing their apply URL, so a transient upstream failure self-heals.
    """
    return run_async(
        _repair_job_apply_urls(
            uuid.UUID(user_id), [uuid.UUID(job_id) for job_id in job_ids]
        )
    )
