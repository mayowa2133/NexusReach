"""Top-level discovery orchestration: seed_default_feeds and discover_jobs."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.job import Job
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.services.occupation_taxonomy import discover_queries_for_occupations
from app.clients import newgrad_jobs_client
from sqlalchemy import func as sa_func
from sqlalchemy import select
from app.utils.startup_jobs import startup_discover_queries
import uuid
from app.services.jobs import constants
from app.services.jobs import curated_boards
from app.services.jobs import search
from app.services.jobs import startup
from app.services.jobs import storage


logger = logging.getLogger(__name__)


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
            total_new += len(stored)
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
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    resolved_occupations = (
        list(occupations)
        if occupations
        else (profile.target_occupations if profile is not None else None)
    )

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
    target_locations = [
        loc for loc in ((profile.target_locations if profile else None) or []) if loc
    ][:constants.DISCOVER_LOCATION_FANOUT]
    expanded_seeds: list[dict] = []
    for seed in search_list:
        expanded_seeds.append(seed)
        if seed.get("location") is None and not seed.get("remote_only"):
            for loc in target_locations:
                expanded_seeds.append({**seed, "location": loc})

    suppress_tech = constants._suppress_tech_sources(resolved_occupations)
    if suppress_tech:
        # All-industry aggregators only - the curated tech employers and
        # tech-leaning boards are noise for nursing / teaching / law / etc.
        discover_sources = ["jsearch", "adzuna", "remotive"]
        logger.info(
            "Discover: routing to broad aggregators only (non-tech occupations: %s)",
            resolved_occupations,
        )
    else:
        discover_sources = ["jsearch", "adzuna", "remotive", "jobicy", "dice", "simplify"]

    for seed in expanded_seeds:
        try:
            stored = await search.search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
                sources=discover_sources,
                limit=constants.DISCOVER_LIMIT_PER_SOURCE,
                occupation_hint=seed.get("occupation"),
            )
            total_new += len(stored)
        except Exception:
            logger.exception("Discover failed for query: %s", seed["query"])

    # 2. newgrad-jobs.com — tech/new-grad-leaning; skip for non-tech occupations.
    if not suppress_tech:
        try:
            raw_newgrad = await newgrad_jobs_client.search_newgrad_jobs()
            ng_stored = await storage._store_raw_jobs(db, user_id, raw_newgrad, profile)
            if ng_stored:
                logger.info("newgrad-jobs discover: %d new jobs", len(ng_stored))
            total_new += len(ng_stored)
        except Exception:
            logger.exception("newgrad-jobs discover failed")

    # 3. Curated ATS boards are all tech companies — skip for non-tech occupations.
    if not suppress_tech:
        try:
            ats_new = await curated_boards._discover_ats_boards(db, user_id)
            total_new += ats_new
        except Exception:
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
            logger.exception("USAJobs government discovery failed")

    logger.info("Discovered %d new jobs for user %s", total_new, user_id)
    return total_new
