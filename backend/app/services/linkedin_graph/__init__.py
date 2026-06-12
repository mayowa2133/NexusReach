"""LinkedIn graph package: import parsing, storage, sync sessions, warm paths.

Module layering (each module imports only from those below it):

    warm_paths         warm-path and follow-signal resolution
    sync               sync sessions, batch imports, status, cleanup
    store              row upserts, lookups, serialization
    matching           company-match predicates over graph rows
    parsing            CSV/ZIP parsing and payload normalization
"""

from app.services.linkedin_graph.matching import (
    connection_matches_company,
    follow_matches_company,
)

from app.services.linkedin_graph.parsing import (
    CSV_EXTENSIONS,
    FOLLOW_ENTITY_TYPES,
    LINKEDIN_GRAPH_SOURCES,
    ZIP_EXTENSIONS,
    dedupe_connection_candidates,
    dedupe_follow_candidates,
    normalize_connection_payload,
    normalize_follow_payload,
    parse_linkedin_connections_csv,
    parse_linkedin_connections_file,
    parse_linkedin_connections_zip,
)

from app.services.linkedin_graph.store import (
    get_connections_by_linkedin_slugs,
    get_connections_for_company,
    get_followed_companies_for_company,
    get_followed_people_by_linkedin_slugs,
    graph_freshness_metadata,
    serialize_connection,
    serialize_follow,
)

from app.services.linkedin_graph.sync import (
    SYNC_STATUS_AWAITING_UPLOAD,
    SYNC_STATUS_COMPLETED,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_IDLE,
    SYNC_STATUS_SYNCING,
    cleanup_orphaned_sync_sessions,
    clear_connections,
    create_sync_session,
    get_status,
    import_batch_with_session,
    import_file,
    import_follow_batch_with_session,
)

from app.services.linkedin_graph.warm_paths import (
    apply_follow_signal_annotations,
    apply_warm_path_annotations,
    resolve_linkedin_signal_for_person,
    resolve_warm_path_for_person,
)

__all__ = [
    "CSV_EXTENSIONS",
    "FOLLOW_ENTITY_TYPES",
    "LINKEDIN_GRAPH_SOURCES",
    "SYNC_STATUS_AWAITING_UPLOAD",
    "SYNC_STATUS_COMPLETED",
    "SYNC_STATUS_FAILED",
    "SYNC_STATUS_IDLE",
    "SYNC_STATUS_SYNCING",
    "ZIP_EXTENSIONS",
    "apply_follow_signal_annotations",
    "apply_warm_path_annotations",
    "cleanup_orphaned_sync_sessions",
    "clear_connections",
    "connection_matches_company",
    "create_sync_session",
    "dedupe_connection_candidates",
    "dedupe_follow_candidates",
    "follow_matches_company",
    "get_connections_by_linkedin_slugs",
    "get_connections_for_company",
    "get_followed_companies_for_company",
    "get_followed_people_by_linkedin_slugs",
    "get_status",
    "graph_freshness_metadata",
    "import_batch_with_session",
    "import_file",
    "import_follow_batch_with_session",
    "normalize_connection_payload",
    "normalize_follow_payload",
    "parse_linkedin_connections_csv",
    "parse_linkedin_connections_file",
    "parse_linkedin_connections_zip",
    "resolve_linkedin_signal_for_person",
    "resolve_warm_path_for_person",
    "serialize_connection",
    "serialize_follow",
]
