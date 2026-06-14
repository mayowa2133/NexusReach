"""USAJobs federal government job search client.

Workday curated boards cover hospitals, universities, banks, and retailers,
but the federal government posts almost exclusively on USAJobs. This client
queries the official USAJobs Search API (https://developer.usajobs.gov) to give
public-sector seekers a real source instead of only broad aggregators.

The API needs a free key (register at developer.usajobs.gov) and a User-Agent
set to the registered email. Both are optional: when unset the client fails
soft and returns ``[]`` (the broad aggregators still serve government roles),
matching the rest of the optional-integration clients in this package.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://data.usajobs.gov/api/search"
_TIMEOUT_SECONDS = 15
_MAX_RESULTS_PER_PAGE = 50


def _configured() -> bool:
    return bool(settings.usajobs_api_key and settings.usajobs_user_agent)


def _normalize_item(item: dict) -> dict | None:
    """Map a USAJobs SearchResultItem to the internal raw-job shape."""
    md = item.get("MatchedObjectDescriptor") or {}
    title = (md.get("PositionTitle") or "").strip()
    if not title:
        return None

    control_number = item.get("MatchedObjectId") or md.get("PositionID") or ""
    apply_uris = md.get("ApplyURI") or []
    apply_url = apply_uris[0] if apply_uris else (md.get("PositionURI") or "")
    url = md.get("PositionURI") or apply_url

    location = md.get("PositionLocationDisplay") or ""
    summary = ((md.get("UserArea") or {}).get("Details") or {}).get("JobSummary") or ""

    return {
        "external_id": f"usajobs_{control_number}" if control_number else "",
        "title": title,
        "company_name": md.get("OrganizationName") or md.get("DepartmentName") or "U.S. Federal Government",
        "location": location,
        "remote": "remote" in f"{location} {title}".lower(),
        "url": url,
        "apply_url": apply_url or None,
        "description": summary,
        "posted_at": md.get("PublicationStartDate") or None,
        "source": "usajobs",
        "ats": None,
    }


async def search_usajobs(
    query: str,
    location: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search USAJobs for federal postings. Fail-soft to ``[]``.

    Returns internal raw-job dicts (source="usajobs"). Requires
    ``NEXUSREACH_USAJOBS_API_KEY`` + ``NEXUSREACH_USAJOBS_USER_AGENT``; without
    them the call is a no-op so government discovery still works (via the broad
    aggregators) and simply gains nothing extra.
    """
    if not _configured():
        logger.debug("USAJobs not configured; skipping (returns [])")
        return []
    if not query:
        return []

    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": settings.usajobs_user_agent,
        "Authorization-Key": settings.usajobs_api_key,
    }
    params: dict[str, str | int] = {
        "Keyword": query,
        "ResultsPerPage": min(max(limit, 1), _MAX_RESULTS_PER_PAGE),
    }
    if location:
        params["LocationName"] = location

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(_SEARCH_URL, params=params, headers=headers)
        if resp.status_code != 200:
            logger.warning("USAJobs returned %d for query %r", resp.status_code, query)
            return []
        data = resp.json()
    except Exception:
        logger.exception("USAJobs search failed for query %r", query)
        return []

    items = (data.get("SearchResult") or {}).get("SearchResultItems") or []
    jobs: list[dict] = []
    for item in items:
        normalized = _normalize_item(item)
        if normalized:
            jobs.append(normalized)
        if len(jobs) >= limit:
            break

    logger.info("USAJobs: %d jobs for query %r", len(jobs), query)
    return jobs


async def discover_usajobs(
    queries: list[str],
    location: str | None = None,
    limit_per_query: int = 25,
) -> list[dict]:
    """Run several USAJobs queries and return combined results. Fail-soft."""
    if not _configured() or not queries:
        return []
    all_jobs: list[dict] = []
    for query in queries:
        all_jobs.extend(await search_usajobs(query, location=location, limit=limit_per_query))
    return all_jobs
