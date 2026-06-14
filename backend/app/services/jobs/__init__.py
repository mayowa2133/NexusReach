"""Job intelligence package — discovery, storage, curated boards, startup, command center.

Split out of the former ``job_service.py`` monolith. ``job_service`` remains a
compatibility shim re-exporting these modules. New code should import from
``app.services.jobs.<module>`` directly.
"""
# ruff: noqa: F401
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
