"""Startup-first discovery: direct boards, ecosystem resolution, startup saved-search refresh."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.job import Job
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.utils.startup_jobs import append_startup_tags
import asyncio
from app.clients import ats
from app.clients import conviction_jobs_client
from app.clients import curated_startups_client
from datetime import datetime
from app.utils.startup_jobs import extract_candidate_links
from app.utils.startup_jobs import is_supported_job_link
from app.utils.startup_jobs import job_matches_any_query
from app.utils.startup_jobs import looks_like_careers_page
from app.clients import public_page_client
from sqlalchemy import select
from app.clients import speedrun_jobs_client
from app.utils.startup_jobs import startup_tags
from datetime import timezone
import uuid
from app.clients import ventureloop_jobs_client
from app.clients import wellfound_jobs_client
from app.clients import yc_jobs_client
from app.services.jobs import constants
from app.services.jobs import search
from app.services.jobs import storage


logger = logging.getLogger(__name__)


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

    # Forward the query so each fetcher applies its built-in filtering instead of
    # returning everything (audit H8). Only pass it when there's a single query —
    # passing one of several would drop jobs matching the other queries, so the
    # multi-query discover path stays broad and relies on the post-hoc filter.
    fetch_query = queries[0] if len(queries) == 1 else None
    results = await asyncio.gather(
        *(fetcher(query=fetch_query, limit=200) for _, fetcher in fetchers),
        return_exceptions=True,
    )
    for (source_key, _fetcher), result in zip(fetchers, results):
        if isinstance(result, BaseException):
            logger.error("Startup direct source failed: %s", source_key, exc_info=result)
        else:
            raw_jobs.extend(result)

    matching_jobs = [job for job in raw_jobs if job_matches_any_query(job, queries)]
    stored = await storage._store_raw_jobs(db, user_id, matching_jobs, profile)
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
    parsed = ats.parse_ats_job_url(candidate_url)
    if not parsed:
        return 0

    if (
        parsed.company_slug
        and parsed.external_id is None
        and parsed.exact_url_only is False
        and parsed.ats_type in {"greenhouse", "lever", "ashby"}
    ):
        adapter = ats.get_adapter(parsed.ats_type)
        if adapter is None or adapter.search_board is None:
            return 0
        raw_jobs = await adapter.search_board(parsed.company_slug, None)
        tagged_jobs = [
            append_startup_tags(job, startup_source)
            for job in raw_jobs
            if job_matches_any_query(job, queries)
        ]
        stored = await storage._store_raw_jobs(db, user_id, tagged_jobs, profile)
        return len(stored)

    exact_jobs = await search.search_ats_jobs(
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
    semaphore = asyncio.Semaphore(constants.STARTUP_LINK_RESOLVE_CONCURRENCY)

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
        for candidate in links[:constants.STARTUP_MAX_RESOLVED_LINKS_PER_COMPANY]:
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
