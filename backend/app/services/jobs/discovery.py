"""Top-level discovery orchestration: seed_default_feeds and discover_jobs."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.job import Job
from app.models.search_preference import SearchPreference
from app.services.occupation_taxonomy import (
    discover_queries_for_occupations,
    occupations_for_keys,
)
from app.clients import newgrad_jobs_client
from sqlalchemy import func as sa_func
from sqlalchemy import select
from app.utils.startup_jobs import startup_discover_queries
import uuid
from app.services.jobs import constants
from app.services.jobs import curated_boards
from app.services.jobs import normalize
from app.services.jobs import search
from app.services.jobs import startup
from app.services.jobs import storage


logger = logging.getLogger(__name__)


def _new_match_count(jobs: list[Job]) -> int:
    """Count inserts without treating refreshed existing matches as new."""
    return sum(1 for job in jobs if getattr(job, "_is_new_job", True))


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
    for seed in constants.DEFAULT_SEED_SEARCHES:
        try:
            stored = await search.search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
            )
            total_new += _new_match_count(stored)
        except Exception:
            logger.exception("Failed to seed default feed: %s", seed["query"])

    logger.info("Seeded %d default jobs for user %s", total_new, user_id)
    return total_new


async def discover_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str] | None = None,
    mode: str = "default",
    occupations: list[str] | None = None,
) -> int:
    """Run a batch of job searches across free sources and ATS boards.

    Unlike seed_default_feeds this always runs — it is the manual
    "Discover Jobs" action.  Deduplication is handled by search.search_jobs
    and search_ats_jobs, so repeat runs are safe.

    Args:
        queries: Optional custom list of free-text search terms. Wins over
                 occupations when both are supplied.
        occupations: Optional list of occupation taxonomy keys. When set,
                     each occupation's default queries are flattened in.
                     Falls back to ``profile.target_occupations`` and finally
                     to ``constants.DISCOVER_QUERIES``.
    """
    # Detached so a mid-discover source rollback can't expire it and make the
    # sync scorer trigger a reload (MissingGreenlet). See load_profile_for_scoring.
    profile = await storage.load_profile_for_scoring(db, user_id)

    profile_occupations = (
        getattr(profile, "target_occupations", None) if profile is not None else None
    )
    if not isinstance(profile_occupations, (list, tuple)):
        profile_occupations = None
    resolved_occupations = (
        list(occupations)
        if occupations
        else (list(profile_occupations) if profile_occupations else None)
    )
    if resolved_occupations:
        valid_occupations = [
            occupation.key for occupation in occupations_for_keys(resolved_occupations)
        ]
        invalid = [
            key for key in resolved_occupations if key not in set(valid_occupations)
        ]
        if invalid:
            logger.warning("Ignoring invalid occupation keys: %s", invalid)
        resolved_occupations = valid_occupations or None
        if not resolved_occupations and not queries:
            # A stale/invalid non-empty profile must never silently become a
            # software-engineering discovery run.
            return 0

    if mode == "startup":
        if queries:
            startup_queries = list(queries)
        else:
            target_roles = profile.target_roles if profile is not None else None
            startup_queries = startup_discover_queries(
                target_roles, occupation_keys=resolved_occupations
            )
        total_new = await startup._discover_startup_direct_sources(db, user_id, profile, startup_queries)
        total_new += await startup._discover_startup_ecosystems(db, user_id, profile, startup_queries)
        # Persist search preferences with mode="startup" so the hourly Celery
        # refresh can re-run the startup discover flow instead of falling back
        # to the default job-board search.
        await startup._ensure_startup_search_preferences(db, user_id, startup_queries)
        await db.commit()
        return total_new

    if queries:
        search_list = [
            {"query": q, "location": None, "remote_only": False} for q in queries
        ]
    elif resolved_occupations:
        search_list = discover_queries_for_occupations(resolved_occupations)
    else:
        search_list = constants.DISCOVER_QUERIES

    total_new = 0

    # 1. Standard job search (JSearch, Dice, Remotive — newgrad excluded here)
    #    newgrad is scraped once unfiltered below instead of 7× with keyword filters
    #    that would discard most results.
    # Preserve the user's explicit location priority order and search every
    # distinct target. The old two-location slice silently ignored the rest of
    # a multi-region search profile.
    target_locations = list(dict.fromkeys(
        loc.strip()
        for loc in ((profile.target_locations if profile else None) or [])
        if isinstance(loc, str) and loc.strip()
    ))
    expanded_seeds: list[dict] = []
    for seed in search_list:
        expanded_seeds.append({**seed, "_location_priority": None})
        if seed.get("location") is None and not seed.get("remote_only"):
            for priority_rank, loc in enumerate(target_locations):
                expanded_seeds.append({
                    **seed,
                    "location": loc,
                    "_location_priority": priority_rank,
                })

    # The engineering-only boards (Dice/Jobicy/Remotive/Simplify) and the tech
    # new-grad scraper / ATS crawl only ever carry tech roles — Remotive even
    # ignores the query. Run them only for engineering-relevant searches; a
    # non-engineering search (marketing, sales, finance, ...) uses the broad
    # all-industry aggregators + the curated non-tech vertical boards, so it can't
    # be polluted with engineering roles that get mis-tagged by the discover hint.
    engineering_relevant = constants._engineering_relevant(resolved_occupations)
    discover_sources = list(constants.ALL_INDUSTRY_DISCOVER_SOURCES)
    if engineering_relevant:
        discover_sources += constants.ENGINEERING_ONLY_DISCOVER_SOURCES
    else:
        logger.info(
            "Discover: all-industry sources only (non-engineering occupations: %s)",
            resolved_occupations,
        )

    try:
        source_factors = await storage.load_source_budget_factors(
            db,
            occupation_keys=resolved_occupations,
        )
    except Exception:
        logger.debug("Source usefulness history unavailable; using exploration budgets", exc_info=True)
        source_factors = {}
    # The Muse fetches by *category*, so on the occupation path every seed of the
    # same occupation resolves to the same category tuple and re-fetches the
    # identical first pages (measured: 4 marketing seeds -> 1 unique batch).
    # Pull it once per occupation in step 1b with the occupation's combined seed
    # budget instead of shallowly per seed.
    occupation_muse_keys: list[str] = []
    if not queries and resolved_occupations and "themuse" in discover_sources:
        discover_sources.remove("themuse")
        occupation_muse_keys = list(dict.fromkeys(resolved_occupations))

    for seed in expanded_seeds:
        try:
            adaptive_source_limits = storage.source_limits_for_budget(
                discover_sources,
                base_limit=constants.DISCOVER_LIMIT_PER_SOURCE,
                factors=source_factors,
                location=seed.get("location"),
                priority_rank=seed.get("_location_priority"),
            )
            stored = await search.search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
                sources=discover_sources,
                limit=constants.DISCOVER_LIMIT_PER_SOURCE,
                occupation_hint=seed.get("occupation"),
                source_limits=adaptive_source_limits,
            )
            total_new += _new_match_count(stored)
        except Exception:
            await db.rollback()
            logger.exception("Discover failed for query: %s", seed["query"])

    # 1b. The Muse, once per occupation with the combined budget of that
    #     occupation's seeds (category-fetch source — see step 1 note). The
    #     deeper single pull harvests pages the per-seed calls never reached.
    for occ in occupation_muse_keys:
        seed_count = sum(1 for s in expanded_seeds if s.get("occupation") == occ) or 1
        occ_query = next(
            (s["query"] for s in search_list if s.get("occupation") == occ and s.get("query")),
            occ.replace("_", " "),
        )
        try:
            stored = await search.search_jobs(
                db,
                user_id,
                query=occ_query,
                sources=["themuse"],
                limit=constants.DISCOVER_LIMIT_PER_SOURCE * seed_count,
                occupation_hint=occ,
                source_limits=storage.source_limits_for_budget(
                    ["themuse"],
                    base_limit=constants.DISCOVER_LIMIT_PER_SOURCE * seed_count,
                    factors=source_factors,
                ),
            )
            total_new += _new_match_count(stored)
        except Exception:
            await db.rollback()
            logger.exception("The Muse occupation discover failed for %s", occ)

    # 2. newgrad-jobs.com — tech/new-grad-leaning; only for engineering searches.
    if engineering_relevant:
        try:
            raw_newgrad = await newgrad_jobs_client.search_newgrad_jobs()
            ng_stored = await storage._store_raw_jobs(db, user_id, raw_newgrad, profile)
            if ng_stored:
                logger.info("newgrad-jobs discover: %d new jobs", len(ng_stored))
            total_new += len(ng_stored)
        except Exception as exc:
            await db.rollback()
            # newgrad-jobs.com is a best-effort scrape; a transient connect/read
            # failure is expected noise, not a bug worth a Sentry error.
            if normalize.is_transient_fetch_error(exc):
                logger.warning("newgrad-jobs discover network error: %s", exc)
            else:
                logger.exception("newgrad-jobs discover failed")

    # 3. The curated ATS registry spans every function. Targeted runs filter
    #    each posting by independent occupation evidence before persistence, so
    #    non-engineering users gain direct-employer coverage without tech noise.
    if engineering_relevant or resolved_occupations:
        try:
            ats_new = await curated_boards._discover_ats_boards(
                db,
                user_id,
                occupation_keys=resolved_occupations,
            )
            total_new += ats_new
        except Exception:
            await db.rollback()
            logger.exception("ATS board discovery failed")

    # 4. Curated non-tech vertical boards (health systems, universities,
    #    banks/insurers, retailers on Workday; federal government on USAJobs).
    #    Occupation-routed and additive: fires whenever the resolved occupations
    #    have a vertical home, independent of the tech-source suppression
    #    decision (a finance seeker isn't suppressed but still wants banks; a
    #    nurse is suppressed and still wants hospitals).
    target_verticals = constants.verticals_for_occupations(resolved_occupations)
    if target_verticals & constants.WORKDAY_VERTICALS:
        try:
            nt_new = await curated_boards._discover_nontech_vertical_boards(
                db, user_id, target_verticals, profile
            )
            total_new += nt_new
            logger.info(
                "Discover: non-tech vertical boards (%s) -> %d new jobs",
                sorted(target_verticals & constants.WORKDAY_VERTICALS),
                nt_new,
            )
        except Exception:
            await db.rollback()
            logger.exception("non-tech vertical board discovery failed")

    # 5. Federal government postings via USAJobs (no-op unless configured).
    if constants.GOVERNMENT_VERTICAL in target_verticals:
        try:
            gov_queries = [s["query"] for s in search_list if s.get("query")]
            gov_new = await curated_boards._discover_government_jobs(db, user_id, gov_queries, profile)
            total_new += gov_new
            if gov_new:
                logger.info("Discover: USAJobs government -> %d new jobs", gov_new)
        except Exception:
            await db.rollback()
            logger.exception("USAJobs government discovery failed")

    logger.info("Discovered %d new jobs for user %s", total_new, user_id)
    return total_new
