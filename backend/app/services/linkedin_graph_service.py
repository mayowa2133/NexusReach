"""LinkedIn graph import, sync-session, and warm-path helpers.

Compatibility shim: the implementation lives in the
``app.services.linkedin_graph`` package. Every name that used to be
defined here is re-exported below so existing imports and test patch
targets keep working. New code should import from the package.
"""
# ruff: noqa: F401

from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.linkedin_graph import (
    LinkedInGraphConnection,
    LinkedInGraphFollow,
    LinkedInGraphSyncRun,
)
from app.models.settings import UserSettings
from app.utils.company_identity import (
    company_family,
    extract_public_identity_hints,
    is_ambiguous_company_name,
    normalize_company_name,
)
from app.utils.linkedin import normalize_linkedin_url
from app.services.linkedin_graph.parsing import (
    CSV_EXTENSIONS,
    FOLLOW_ENTITY_TYPES,
    LINKEDIN_GRAPH_SOURCES,
    ZIP_EXTENSIONS,
    _canonicalize_header,
    _canonicalize_row,
    _clean_text,
    _company_slug_from_url,
    _find_csv_header_index,
    _linkedin_slug_from_url,
    _lookup_value,
    _normalize_company_linkedin_url,
    _zip_connection_candidates,
    dedupe_connection_candidates,
    dedupe_follow_candidates,
    normalize_connection_payload,
    normalize_follow_payload,
    parse_linkedin_connections_csv,
    parse_linkedin_connections_file,
    parse_linkedin_connections_zip,
)
from app.services.linkedin_graph.matching import (
    connection_matches_company,
    follow_matches_company,
)
from app.services.linkedin_graph.store import (
    graph_freshness_metadata,
    _connection_count,
    _find_existing_connection,
    _find_existing_follow,
    _follow_counts,
    _get_or_create_user_settings,
    _merge_connection,
    _merge_follow,
    _token_hash,
    _upsert_connections,
    _upsert_follows,
    _utcnow,
    get_connections_by_linkedin_slugs,
    get_connections_for_company,
    get_followed_companies_for_company,
    get_followed_people_by_linkedin_slugs,
    serialize_connection,
    serialize_follow,
)
from app.services.linkedin_graph.sync import (
    SYNC_STATUS_AWAITING_UPLOAD,
    SYNC_STATUS_COMPLETED,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_IDLE,
    SYNC_STATUS_SYNCING,
    _latest_run,
    _serialize_run,
    _sync_run_for_token,
    cleanup_orphaned_sync_sessions,
    clear_connections,
    create_sync_session,
    get_status,
    import_batch_with_session,
    import_file,
    import_follow_batch_with_session,
)
from app.services.linkedin_graph.warm_paths import (
    _score_bridge_relevance,
    _select_best_bridge,
    _warm_path_priority,
    apply_follow_signal_annotations,
    apply_warm_path_annotations,
    resolve_linkedin_signal_for_person,
    resolve_warm_path_for_person,
)











































































































