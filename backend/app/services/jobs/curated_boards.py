"""Curated board discovery: tech ATS boards, non-tech Workday verticals, USAJobs government."""

import logging
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.job import Job
from app.models.profile import Profile
from app.clients import amazon_client
from app.clients import apple_client
import asyncio
from app.clients import ats
from app.clients import google_client
from app.utils.startup_jobs import job_matches_any_query
from app.clients import lever_scrape_client
from app.clients import meta_client
from app.clients import microsoft_client
from app.utils.job_metadata import normalize_job_metadata
from sqlalchemy import select
from app.clients import tesla_client
from app.clients import usajobs_client
import uuid
from app.clients import workday_client
from app.services.jobs import constants
from app.services.jobs import discovered_boards
from app.services.jobs import normalize
from app.services.jobs import storage


logger = logging.getLogger(__name__)


async def _discover_ats_boards(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit_per_board: int = 50,
    refresh_run_id: uuid.UUID | None = None,
) -> int:
    """Pull jobs from curated Greenhouse, Ashby, Lever, and Workday boards."""
    source_payloads, source_stats = await fetch_curated_ats_source_payloads(
        limit_per_board=limit_per_board
    )
    return await store_curated_ats_payloads_for_user(
        db,
        user_id,
        source_payloads=source_payloads,
        source_stats=source_stats,
        preferences=None,
        refresh_run_id=refresh_run_id,
    )


async def _discover_nontech_vertical_boards(
    db: AsyncSession,
    user_id: uuid.UUID,
    verticals: set[str],
    profile,
    limit_per_company: int = 40,
) -> int:
    """Pull jobs from curated Workday employers in the given verticals.

    The non-tech analog of ``_discover_ats_boards``: health systems,
    universities, banks/insurers, and retailers on Workday. Occupation-routed
    by ``verticals`` so only relevant employers are fetched. Government is not
    handled here (it has no curated Workday tenant — see
    ``_discover_government_jobs``). Fails soft.
    """
    workday_verticals = {v for v in verticals if v in constants.WORKDAY_VERTICALS}
    if not workday_verticals:
        return 0
    try:
        raw_jobs = await workday_client.discover_all_nontech_workday(
            limit_per_company=limit_per_company, verticals=workday_verticals
        )
    except Exception:
        logger.exception("non-tech vertical board discovery failed")
        return 0
    stored = await storage._store_raw_jobs(db, user_id, raw_jobs, profile)
    return len(stored)


async def _discover_government_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str],
    profile,
    limit_per_query: int = 25,
) -> int:
    """Pull federal postings from USAJobs for government seekers. Fails soft.

    USAJobs is the official federal board; agencies don't post on the curated
    Workday tenants, so the ``government`` vertical routes here instead. No-op
    when USAJobs is unconfigured (the broad aggregators still serve gov roles).
    """
    seeds = [q for q in dict.fromkeys(queries) if q][:4]
    if not seeds:
        return 0
    try:
        raw_jobs = await usajobs_client.discover_usajobs(seeds, limit_per_query=limit_per_query)
    except Exception:
        logger.exception("USAJobs government discovery failed")
        return 0
    if not raw_jobs:
        return 0
    stored = await storage._store_raw_jobs(db, user_id, raw_jobs, profile)
    return len(stored)


async def fetch_curated_ats_source_payloads(
    limit_per_board: int = 50,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Fetch curated ATS/proprietary sources once for fanout to users."""
    # Bumped from 8: the registry now includes ~900+ auto-discovered boards, and
    # these are independent ATS APIs, so more concurrency keeps the crawl fast.
    semaphore = asyncio.Semaphore(24)
    source_fetches = []

    async def run_source(source_key: str, fetcher) -> tuple[str, list[dict], dict]:
        stat = normalize._source_stat(source_key)
        try:
            async with semaphore:
                raw_jobs = await fetcher()
            for job in raw_jobs:
                job["_source_run_key"] = source_key
            stat["raw_count"] = len(raw_jobs)
            normalize._finish_source_stat(stat, status="success")
            return source_key, raw_jobs, stat
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning(
                "Curated job source transient failure: %s (%s)",
                source_key,
                exc.__class__.__name__,
            )
            normalize._finish_source_stat(
                stat,
                status="failed",
                error=f"{exc.__class__.__name__}: {exc}",
            )
            return source_key, [], stat
        except Exception as exc:
            logger.exception("Curated job source failed: %s", source_key)
            normalize._finish_source_stat(stat, status="failed", error=str(exc))
            return source_key, [], stat

    for board in constants.ATS_DISCOVER_BOARDS:
        source_key = f"{board['ats']}:{board['slug']}"

        async def fetch_board(board=board) -> list[dict]:
            adapter = ats.get_adapter(board["ats"])
            return (
                await adapter.search_board(board["slug"], limit_per_board)
                if adapter and adapter.search_board is not None
                else []
            )

        source_fetches.append(run_source(source_key, fetch_board))

    for slug in constants.LEVER_DISCOVER_SLUGS:
        source_key = f"lever:{slug}"

        async def fetch_lever(slug=slug) -> list[dict]:
            return await lever_scrape_client.search_lever_html(slug, limit=limit_per_board)

        source_fetches.append(run_source(source_key, fetch_lever))

    # NOTE: the ~900 auto-discovered boards are NOT fetched here — holding every
    # board's jobs in one payload dict OOM-kills the worker at that scale. They're
    # crawled in memory-bounded chunks by `crawl_and_store_discovered_boards`.

    async def fetch_workday() -> list[dict]:
        return await workday_client.discover_all_workday(limit_per_company=20)

    source_fetches.append(run_source("workday:curated", fetch_workday))

    proprietary_sources: list[tuple[str, object]] = [
        ("amazon", amazon_client.search_amazon_jobs),
        ("microsoft", microsoft_client.search_microsoft_jobs),
        ("apple", apple_client.search_apple_jobs),
        ("google", google_client.search_google_jobs),
        ("tesla", tesla_client.search_tesla_jobs),
        ("meta", meta_client.search_meta_jobs),
    ]
    for source_key, fetcher in proprietary_sources:
        async def fetch_proprietary(fetcher=fetcher) -> list[dict]:
            return await fetcher(limit=20)

        source_fetches.append(run_source(source_key, fetch_proprietary))

    source_payloads: dict[str, list[dict]] = {}
    source_stats: list[dict] = []
    for source_key, raw_jobs, stat in await asyncio.gather(*source_fetches):
        source_payloads[source_key] = raw_jobs
        source_stats.append(stat)

    return source_payloads, source_stats


def job_matches_refresh_preferences(
    raw_job: dict,
    preferences,
) -> bool:
    """Return whether a crawled board job matches at least one saved search."""
    normalized = normalize_job_metadata(dict(raw_job))
    for pref in preferences:
        if not getattr(pref, "enabled", True):
            continue
        if (getattr(pref, "mode", "default") or "default") != "default":
            continue
        query = (getattr(pref, "query", "") or "").strip()
        if query and not job_matches_any_query(normalized, [query]):
            continue
        if not normalize._job_matches_refresh_filters(
            normalized,
            location=getattr(pref, "location", None),
            remote_only=bool(getattr(pref, "remote_only", False)),
        ):
            continue
        return True
    return False


def _source_run_key_for_stored_job(job: Job) -> str:
    if job.ats in {"greenhouse", "ashby", "lever"} and job.ats_slug:
        return f"{job.ats}:{job.ats_slug}"
    if job.source == "workday":
        return "workday:curated"
    if job.source == "google_careers":
        return "google"
    if job.source == "apple_jobs":
        return "apple"
    return job.source or job.ats or "unknown"


async def store_curated_ats_payloads_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    source_payloads: dict[str, list[dict]],
    source_stats: list[dict],
    preferences=None,
    refresh_run_id: uuid.UUID | None = None,
) -> int:
    """Store one global ATS crawl for a user after saved-search filtering."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    filtered_jobs: list[dict] = []
    matched_counts_by_source: dict[str, int] = {}
    for source_key, jobs in source_payloads.items():
        for raw_job in jobs:
            if preferences is not None and not job_matches_refresh_preferences(raw_job, preferences):
                continue
            matched = dict(raw_job)
            matched["_source_run_key"] = source_key
            filtered_jobs.append(matched)
            matched_counts_by_source[source_key] = matched_counts_by_source.get(source_key, 0) + 1

    stored = await storage._store_raw_jobs(db, user_id, filtered_jobs, profile)
    stored_counts_by_source: dict[str, int] = {}
    for job in stored:
        source_key = _source_run_key_for_stored_job(job)
        stored_counts_by_source[source_key] = stored_counts_by_source.get(source_key, 0) + 1

    user_source_stats: list[dict] = []
    for stat in source_stats:
        user_stat = dict(stat)
        source_key = user_stat["source"]
        if user_stat.get("status") == "success":
            user_stat["raw_count"] = matched_counts_by_source.get(source_key, 0)
        user_stat["new_count"] = stored_counts_by_source.get(source_key, 0)
        user_source_stats.append(user_stat)

    await storage._record_source_runs(
        db, refresh_run_id=refresh_run_id, source_stats=user_source_stats
    )
    return len(stored)


async def _fetch_board_payloads(
    boards: list[dict], limit_per_board: int
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Fetch one chunk of auto-discovered boards through the ATS adapters.

    Stamps the verified company name (the board APIs sometimes return only the
    slug) and fails soft per board.
    """
    semaphore = asyncio.Semaphore(12)

    async def one(board: dict) -> tuple[str, list[dict], dict]:
        source_key = f"{board['ats']}:{board['slug']}"
        stat = normalize._source_stat(source_key)
        try:
            adapter = ats.get_adapter(board["ats"])
            async with semaphore:
                jobs = (
                    await adapter.search_board(board["slug"], limit_per_board)
                    if adapter and adapter.search_board is not None
                    else []
                )
            for job in jobs:
                job["company_name"] = board["company"]
                job["_source_run_key"] = source_key
            stat["raw_count"] = len(jobs)
            normalize._finish_source_stat(stat, status="success")
            return source_key, jobs, stat
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            normalize._finish_source_stat(stat, status="failed", error=exc.__class__.__name__)
            return source_key, [], stat
        except Exception as exc:
            logger.exception("discovered board failed: %s", source_key)
            normalize._finish_source_stat(stat, status="failed", error=str(exc))
            return source_key, [], stat

    payloads: dict[str, list[dict]] = {}
    stats: list[dict] = []
    for source_key, jobs, stat in await asyncio.gather(*(one(b) for b in boards)):
        payloads[source_key] = jobs
        stats.append(stat)
    return payloads, stats


async def crawl_and_store_discovered_boards(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    preferences=None,
    limit_per_board: int = 25,
    chunk_size: int = 60,
    refresh_run_id: uuid.UUID | None = None,
) -> int:
    """Crawl the ~900 auto-discovered boards in memory-bounded chunks.

    Fetching every board at once held ~20k jobs (with full HTML descriptions) in
    memory and OOM-killed the worker (SIGKILL). Instead we fetch a chunk, store
    it, and free it before the next chunk — peak memory is bounded to ~one chunk.
    """
    boards = list(discovered_boards.load_discovered_boards())
    total = 0
    for start in range(0, len(boards), chunk_size):
        chunk = boards[start:start + chunk_size]
        payloads, stats = await _fetch_board_payloads(chunk, limit_per_board)
        try:
            total += await store_curated_ats_payloads_for_user(
                db,
                user_id,
                source_payloads=payloads,
                source_stats=stats,
                preferences=preferences,
                refresh_run_id=refresh_run_id,
            )
        except Exception:
            await db.rollback()
            logger.exception("discovered-board chunk store failed (user %s)", user_id)
    return total
