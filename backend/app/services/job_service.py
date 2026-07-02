"""Job intelligence service.

Compatibility shim: the implementation now lives in the ``app.services.jobs``
package (constants, normalize, storage, search, curated_boards, command_center,
startup, discovery). Every public and private name that used to be defined here
is re-exported below so existing imports, attribute access, and test patch
targets keep working. New code should import from ``app.services.jobs.<module>``.
"""
# ruff: noqa: F401, E402

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

from sqlalchemy import Date, func as sa_func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import (
    adzuna_client,
    amazon_client,
    apple_client,
    ats,
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
    usajobs_client,
    ventureloop_jobs_client,
    wellfound_jobs_client,
    workday_client,
    yc_jobs_client,
)
from app.models.company import Company
from app.models.job import Job
from app.models.job_refresh_run import JobSourceRun
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
from app.utils.company_identity import normalize_company_name
from app.utils.job_metadata import (
    country_code_for_name,
    geocode_location_query,
    normalize_job_metadata,
)
from app.services.occupation_taxonomy import (
    OCCUPATION_TAG_PREFIX,
    discover_queries_for_occupations,
    occupation_tag,
    occupation_tags_for_job,
)
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

from app.services.jobs.constants import (
    DEFAULT_SEARCH_SOURCES,
    STARTUP_BOARD_SOURCES,
    STARTUP_LINK_RESOLVE_CONCURRENCY,
    DISCOVER_LIMIT_PER_SOURCE,
    DISCOVER_LOCATION_FANOUT,
    STARTUP_MAX_RESOLVED_LINKS_PER_COMPANY,
    APPLY_URL_REPAIR_MAX_JOBS,
    INDUSTRY_BOUND_NONTECH_OCCUPATIONS,
    _suppress_tech_sources,
    OCCUPATION_VERTICALS,
    WORKDAY_VERTICALS,
    GOVERNMENT_VERTICAL,
    verticals_for_occupations,
    DEFAULT_SEED_SEARCHES,
    DISCOVER_QUERIES,
    ATS_DISCOVER_BOARDS,
    LEVER_DISCOVER_SLUGS,
)
from app.services.jobs.normalize import (
    EARTH_RADIUS_KM,
    _fingerprint,
    _normalized_pref_location,
    _canonical_job_url,
    _result_first,
    _utcnow,
    _source_stat,
    _finish_source_stat,
    summarize_source_stats,
    _job_source_key,
    _job_identity_key,
    _coerce_posted_at,
    _POSTED_DATE_RE,
    _parse_posted_date,
    _experience_level_for_job,
    _employment_type_for_job,
    _apply_if_present,
    _distance_km_expression,
    _with_extra_tags,
    _adzuna_country_for_location,
    _job_matches_refresh_filters,
)
from app.services.jobs.storage import (
    _refresh_existing_job,
    _build_job,
    _find_existing_job,
    _score_job,
    _record_source_runs,
    _load_known_startup_company_names,
    _infer_startup_tags_for_job,
    _infer_occupation_tags_for_job,
    _store_raw_jobs,
    mark_stale_jobs_for_user,
    _maybe_auto_prospect,
)
from app.services.jobs.search import (
    _fetch_jobs_for_source,
    search_jobs,
    search_ats_jobs,
    _repair_missing_apply_urls,
)
from app.services.jobs.curated_boards import (
    _discover_ats_boards,
    _discover_nontech_vertical_boards,
    _discover_government_jobs,
    fetch_curated_ats_source_payloads,
    job_matches_refresh_preferences,
    _source_run_key_for_stored_job,
    store_curated_ats_payloads_for_user,
)
from app.services.jobs.command_center import (
    toggle_job_starred,
    get_jobs,
    get_description_previews,
    count_warming_jobs,
    update_job_stage,
    update_interview_rounds,
    update_offer_details,
    get_job,
    get_job_command_center,
    _determine_job_next_action,
)
from app.services.jobs.startup import (
    _resolve_supported_job_links,
    _discover_startup_direct_sources,
    _import_startup_candidate_link,
    _discover_startup_ecosystem_entries,
    _discover_startup_ecosystems,
    run_startup_refresh_for_query,
    _ensure_startup_search_preferences,
)
from app.services.jobs.discovery import (
    seed_default_feeds,
    discover_jobs,
)
