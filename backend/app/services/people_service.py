"""People discovery service for company and job-aware search.

Compatibility shim: the implementation now lives in the
``app.services.people`` package. Every public and private name that
used to be defined here is re-exported below so existing imports,
attribute access, and test patch targets keep working. New code should
import from ``app.services.people.<module>`` directly.
"""
# ruff: noqa: F401

import asyncio
import copy
import logging
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, TypeVar
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import apollo_client, github_client, proxycurl_client, search_router_client, tavily_search_client, theorg_client
from app.config import settings
from app.models.company import Company
from app.models.job import Job
from app.models.person import Person
from app.services import linkedin_graph_service
from app.services.employment_verification_service import verify_people_current_company
from app.services.theorg_discovery_service import discover_theorg_candidates
from app.utils.company_identity import (
    build_public_identity_hints,
    canonical_company_display_name,
    effective_public_identity_slugs,
    extract_public_identity_hints,
    is_ambiguous_company_name,
    is_compatible_public_identity_slug,
    matches_public_company_identity,
    normalize_company_name,
    should_trust_company_enrichment,
)
from app.utils.job_context import (
    JobContext,
    build_job_geo_terms,
    extract_job_context,
    normalize_job_locations,
)
from app.services.occupation_taxonomy import (
    is_engineering_flavored as _occupation_is_engineering_flavored,
    manager_title_seeds_for as _occupation_manager_titles,
    peer_title_seeds_for as _occupation_peer_titles,
)
from app.utils.linkedin import normalize_linkedin_url
from app.utils.relevance_scorer import score_candidate_relevance

from app.services.people.buckets import (
    _append_bucket,
    _apply_match_metadata,
    _backfill_sparse_hiring_manager_bucket,
    _bucketed_linkedin_slugs,
    _dedupe_bucket_assignments,
    _detached_person_copy,
    _finalize_bucketed,
)

from app.services.people.candidates import (
    DEFAULT_TARGET_COUNT_PER_BUCKET,
    MAX_TARGET_COUNT_PER_BUCKET,
    _balanced_candidate_mix,
    _candidate_key,
    _clamp_target_count_per_bucket,
    _count_linkedin_candidates,
    _debug_candidate_summary,
    _dedupe_candidate_bucket_groups,
    _dedupe_candidates,
    _expand_peer_candidates,
    _has_local_geo_match,
    _has_recruiter_lead_candidate,
    _interactive_enrichment_limit_for_target,
    _limit_interactive_bucket,
    _minimum_results_for_target,
    _needs_more_bucket_candidates,
    _needs_more_bucket_size_only,
    _prepare_candidates,
    _prepare_limit_for_target,
    _search_candidates,
    _search_limit_for_target,
    _should_expand_with_theorg,
    _should_run_manager_geo_recovery,
    _should_run_peer_targeted_recovery,
    _should_run_recruiter_targeted_recovery,
)

from app.services.people.classify import (
    _classify_org_level,
    _classify_person,
    _compute_match_metadata,
)

from app.services.people.company_match import (
    AMBIGUOUS_COMPANY_NEGATIVE_SUFFIXES,
    COMPANY_NEGATIVE_TERMS,
    CURRENT_TRUSTED_PUBLIC_HOSTS,
    CURRENT_TRUSTED_SOURCES,
    FORMER_COMPANY_PATTERNS,
    PUBLIC_DIRECTORY_TERMS,
    PUBLIC_WEB_SOURCES,
    _candidate_matches_company,
    _classify_employment_status,
    _linkedin_company_match,
    _mentions_company,
    _public_url_matches_company,
    _trusted_public_match,
    _trusted_public_peer_match,
)

from app.services.people.context import (
    _bucket_geo_terms,
    _build_roles_context,
    _candidate_geo_signal_match,
    _candidate_location_value,
    _location_match_rank,
)

from app.services.people.identity import (
    _contains_any_keyword,
    _dedupe_text,
    _identity_tokens,
    _is_linkedin_public_profile,
    _keyword_in_text,
    _linkedin_backfill_name_variants,
    _linkedin_profile_host,
    _name_match_score,
    _normalize_identity,
    _normalize_name_for_matching,
    _public_profile_host,
    _public_profile_url,
    _slugify,
)

from app.services.people.linkedin_backfill import (
    _backfill_linkedin_profiles,
    _backfill_top_candidates,
    _choose_linkedin_backfill_match,
    _linkedin_backfill_metadata,
    _linkedin_backfill_search_titles,
    _linkedin_backfill_team_keywords,
    _linkedin_role_match,
    _linkedin_title_match_score,
    _mark_linkedin_backfill_deferred,
)

from app.services.people.persistence import (
    _normalize_linkedin_page_capture,
    _store_person,
    get_or_create_company,
    get_saved_people,
    get_search_history,
    persist_linkedin_page_capture,
)

from app.services.people.ranking import (
    SOURCE_PRIORITY,
    _bucket_role_fit_rank,
    _candidate_bucket_assignment_rank,
    _candidate_bucket_role_fit_rank,
    _candidate_sort_key,
    _company_match_confidence,
    _compute_usefulness_score,
    _confidence_rank,
    _context_rank,
    _heuristic_relevance_score,
    _linkedin_signal_rank,
    _manager_person_title_specificity_rank,
    _manager_title_specificity_rank,
    _match_rank,
    _org_rank,
    _peer_person_title_alignment_rank,
    _peer_title_alignment_rank,
    _person_location_match_rank,
    _recency_rank,
    _recruiter_person_scope_rank,
    _recruiter_scope_rank_from_text,
    _score_contextual_candidates,
    _score_contextual_candidates_fast,
    _seniority_fit_rank,
    _source_rank,
    _team_keyword_match_rank,
    _warm_path_rank,
)

from app.services.people.service import (
    _debug_person_summary,
    _record_timing,
    enrich_person_from_linkedin,
    search_people_at_company,
    search_people_for_job,
)

from app.services.people.theorg_recovery import (
    _candidate_public_identity_slug,
    _candidate_theorg_slug_candidates,
    _merge_company_public_identity_slugs,
    _recover_candidate_titles,
    _recover_title_from_theorg_page,
    _saved_theorg_slug_candidates,
    _title_recovery_metadata,
)

from app.services.people.titles import (
    CONTROLLED_LEAD_KEYWORDS,
    DIRECTOR_PLUS_KEYWORDS,
    GENERIC_PEOPLE_TITLE_KEYWORDS,
    MANAGER_TITLE_KEYWORDS,
    RECRUITER_ADJACENT_KEYWORDS,
    RECRUITER_TITLE_KEYWORDS,
    ROLE_HINT_KEYWORDS,
    SENIORITY_ORDER,
    SENIOR_IC_FALLBACK_KEYWORDS,
    SENIOR_MANAGER_LEVELS,
    TALENT_TITLE_KEYWORDS,
    WEAK_TITLE_PLACEHOLDERS,
    _IC_MANAGER_PATTERNS,
    _SENIOR_LEADERSHIP_PREFIXES,
    _allow_director_plus,
    _broaden_peer_titles_for_retry,
    _candidate_seniority_level,
    _companywide_manager_titles,
    _companywide_peer_titles,
    _companywide_recruiter_titles,
    _generic_manager_title,
    _initial_manager_titles,
    _is_adjacent_recruiter_like,
    _is_ic_manager_title,
    _is_manager_like,
    _is_recruiter_like,
    _is_senior_ic_fallback,
    _manager_candidate_has_engineering_context,
    _manager_context_search_titles,
    _manager_geo_recovery_keywords,
    _manager_geo_recovery_titles,
    _manager_seniority_filters,
    _peer_seniority_filters,
    _peer_targeted_recovery_keywords,
    _peer_targeted_recovery_titles,
    _peer_title_variants_for_seniority,
    _prioritize_titles_for_search,
    _recover_title_from_snippet,
    _recruiter_targeted_recovery_keywords,
    _recruiter_targeted_recovery_titles,
    _role_like_title,
    _sanitize_search_keywords,
    _strip_seniority_prefix,
    _title_is_weak,
    _title_looks_like_company_only,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")
