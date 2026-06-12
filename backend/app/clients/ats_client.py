"""ATS ingestion clients for board-backed and exact-job job URLs."""
# ruff: noqa: F401

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import httpx

from app.clients import crawl4ai_client, firecrawl_client
from app.utils.job_metadata import parse_json_ld_base_salary
from app.utils.url_safety import is_safe_public_url, safe_get
from app.clients.ats.html import (
    WORKDAY_JOB_TOKEN_RE,
    _workday_company_slug,
    CANONICAL_LINK_RE,
    COMMON_SUBDOMAINS,
    HEADING_RE,
    JSON_LD_RE,
    STATIC_ROUTER_RE,
    TAG_RE,
    TITLE_RE,
    WHITESPACE_RE,
    _clean_url,
    _coerce_posted_at,
    _display_company_slug,
    _domain_root,
    _epoch_ms_to_iso,
    _extract_canonical_link,
    _extract_heading,
    _extract_json_ld_job,
    _extract_meta_content,
    _extract_static_router_payload,
    _extract_title,
    _find_attr,
    _host_ats_label,
    _humanize_company_slug,
    _job_posting_candidates,
    _json_ld_company,
    _json_ld_location,
    _normalize_text,
    _string_list,
    _strip_tags,
)
from app.clients.ats.urls import (
    ParsedATSJobURL,
    _parse_apple_jobs_url,
    _parse_ashby_url,
    _parse_generic_exact_url,
    _parse_greenhouse_url,
    _parse_icims_url,
    _parse_lever_url,
    _parse_workable_url,
    _parse_workday_url,
)
from app.clients.ats.normalize import (
    WORKDAY_COMPANY_NOISE_TOKENS,
    _apple_description,
    _apple_location,
    _cleanup_generic_title,
    _company_name_from_keywords,
    _generic_company_name,
    _job_richness_score,
    _normalize_apple_job,
    _normalize_exact_page,
    _normalize_generic_exact_job,
    _normalize_icims_job,
    _normalize_json_ld_job,
    _normalize_workday_job,
    _workday_company_name,
    _workday_location_from_json_ld,
    _workday_page_matches,
)
from app.clients.ats.boards import (
    _workable_location,
    search_ashby,
    search_greenhouse,
    search_lever,
    search_workable,
)
from app.clients.ats.exact import (
    ExactJobFetchError,
    _fetch_apple_exact_job,
    _fetch_direct_exact_page,
    _fetch_exact_job_with_normalizer,
    _fetch_exact_page_candidates,
    _fetch_generic_exact_job,
    _fetch_icims_exact_job,
    _fetch_workable_exact_job,
    _fetch_workday_exact_job,
    _probe_workday_job_redirect,
)
from app.clients.ats.registry import (
    ATSAdapter,
    ATS_ADAPTERS,
    ATS_ADAPTERS_BY_TYPE,
    fetch_exact_job,
    get_adapter,
    parse_ats_job_url,
)



































































































































