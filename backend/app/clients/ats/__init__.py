"""ATS ingestion package: board search, exact-job fetch, URL parsing.

Module layering (each module imports only from those below it):

    registry           adapter table and public entry points
    exact              exact-job page fetching pipeline
    boards             board-backed search APIs
    normalize          raw page payload -> job dict converters
    urls               job URL parsing into ParsedATSJobURL
    html               generic HTML/text/URL primitives
"""

from app.clients.ats.boards import (
    search_ashby,
    search_greenhouse,
    search_lever,
    search_workable,
)
from app.clients.ats.exact import ExactJobFetchError
from app.clients.ats.registry import (
    ATS_ADAPTERS,
    ATS_ADAPTERS_BY_TYPE,
    ATSAdapter,
    fetch_exact_job,
    get_adapter,
    parse_ats_job_url,
)
from app.clients.ats.urls import ParsedATSJobURL

__all__ = [
    "ATS_ADAPTERS",
    "ATS_ADAPTERS_BY_TYPE",
    "ATSAdapter",
    "ExactJobFetchError",
    "ParsedATSJobURL",
    "fetch_exact_job",
    "get_adapter",
    "parse_ats_job_url",
    "search_ashby",
    "search_greenhouse",
    "search_lever",
    "search_workable",
]
