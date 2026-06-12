"""ATS adapter registry and public entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable
from app.clients.ats.boards import search_ashby, search_greenhouse, search_lever
from app.clients.ats.exact import ExactJobFetchError, _fetch_apple_exact_job, _fetch_generic_exact_job, _fetch_icims_exact_job, _fetch_workable_exact_job, _fetch_workday_exact_job
from app.clients.ats.urls import ParsedATSJobURL, _parse_apple_jobs_url, _parse_ashby_url, _parse_generic_exact_url, _parse_greenhouse_url, _parse_icims_url, _parse_lever_url, _parse_workable_url, _parse_workday_url




@dataclass(frozen=True)
class ATSAdapter:
    ats_type: str
    parse_url: Callable[[str], ParsedATSJobURL | None]
    search_board: Callable[[str, int | None], Awaitable[list[dict]]] | None = None
    fetch_exact: Callable[[ParsedATSJobURL], Awaitable[list[dict]]] | None = None


ATS_ADAPTERS = (
    ATSAdapter("greenhouse", _parse_greenhouse_url, search_board=search_greenhouse),
    ATSAdapter("lever", _parse_lever_url, search_board=search_lever),
    ATSAdapter("ashby", _parse_ashby_url, search_board=search_ashby),
    ATSAdapter("workable", _parse_workable_url, fetch_exact=_fetch_workable_exact_job),
    ATSAdapter("apple_jobs", _parse_apple_jobs_url, fetch_exact=_fetch_apple_exact_job),
    ATSAdapter("workday", _parse_workday_url, fetch_exact=_fetch_workday_exact_job),
    ATSAdapter("icims", _parse_icims_url, fetch_exact=_fetch_icims_exact_job),
    ATSAdapter("generic_exact", _parse_generic_exact_url, fetch_exact=_fetch_generic_exact_job),
)


ATS_ADAPTERS_BY_TYPE = {adapter.ats_type: adapter for adapter in ATS_ADAPTERS}


def parse_ats_job_url(job_url: str) -> ParsedATSJobURL | None:
    """Parse a job URL into adapter-specific ATS metadata."""
    for adapter in ATS_ADAPTERS:
        parsed = adapter.parse_url(job_url)
        if parsed:
            return parsed
    return None


def get_adapter(ats_type: str | None) -> ATSAdapter | None:
    if not ats_type:
        return None
    return ATS_ADAPTERS_BY_TYPE.get(ats_type)


async def fetch_exact_job(parsed_job_url: ParsedATSJobURL) -> list[dict]:
    """Fetch a single job posting from an exact job URL adapter."""
    adapter = get_adapter(parsed_job_url.ats_type)
    if not adapter or adapter.fetch_exact is None:
        raise ExactJobFetchError("Unsupported exact job posting URL.")

    jobs = await adapter.fetch_exact(parsed_job_url)
    if not jobs:
        raise ExactJobFetchError("We found the page, but couldn't extract enough job details from it.")
    return jobs
