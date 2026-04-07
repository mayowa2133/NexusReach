"""Meta Careers job search client.

Meta's careers site (metacareers.com) exposes an internal GraphQL API at
``/api/graphql/`` that is publicly accessible without authentication.
Each request requires an LSD token extracted from a page load, but no
cookies or login session are needed.

Two-step flow:
  1. GET /jobsearch to extract the short-lived ``lsd`` token from HTML.
  2. POST /api/graphql/ with the search query using that token.

The search query returns all open Meta positions (id, title, locations,
teams) in a single response.  A separate detail call per job is available
but skipped in the bulk flow to keep latency reasonable.

If the LSD token or GraphQL response format changes on a Meta deploy,
the client falls back to an empty list gracefully.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.metacareers.com"
_JOBSEARCH_URL = f"{_BASE_URL}/jobsearch"
_GRAPHQL_URL = f"{_BASE_URL}/api/graphql/"

# doc_id for CareersJobSearchResultsDataQuery — stable across non-deploy intervals
_SEARCH_DOC_ID = "29615178951461218"
_SEARCH_QUERY_NAME = "CareersJobSearchResultsDataQuery"

# Regex to extract LSD token from page HTML
# Appears as: "LSD",[],{"token":"<value>"}
_LSD_RE = re.compile(r'"LSD"[^{]*\{"token":"([^"]+)"')

_HEADERS_PAGE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _graphql_headers(lsd_token: str) -> dict[str, str]:
    return {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": _BASE_URL,
        "Referer": _JOBSEARCH_URL,
        "User-Agent": _HEADERS_PAGE["User-Agent"],
        "X-FB-LSD": lsd_token,
        "X-FB-Friendly-Name": _SEARCH_QUERY_NAME,
    }


async def _fetch_lsd_token(client: httpx.AsyncClient) -> str | None:
    """GET the jobsearch page and extract the LSD token."""
    try:
        resp = await client.get(_JOBSEARCH_URL, headers=_HEADERS_PAGE, timeout=15)
        if resp.status_code != 200:
            logger.debug("Meta LSD page returned %d", resp.status_code)
            return None
        match = _LSD_RE.search(resp.text)
        if not match:
            logger.debug("Meta LSD token not found in page HTML")
            return None
        return match.group(1)
    except Exception:
        logger.exception("Meta LSD token fetch failed")
        return None


def _build_search_variables(search_text: str) -> str:
    """Build the ``variables`` JSON string for the search query."""
    search_input: dict = {
        "q": search_text or "",
        "divisions": [],
        "offices": [],
        "roles": [],
        "leadership_levels": [],
        "is_remote_only": False,
        "sort_by_new": True,
        "results_per_page": None,
        "teams": [],
        "sub_teams": [],
    }
    return json.dumps({"search_input": search_input})


def _build_graphql_body(lsd_token: str, search_text: str) -> str:
    """Build form-encoded body for the GraphQL request."""
    params = {
        "av": "0",
        "__user": "0",
        "__a": "1",
        "__comet_req": "15",
        "lsd": lsd_token,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": _SEARCH_QUERY_NAME,
        "variables": _build_search_variables(search_text),
        "doc_id": _SEARCH_DOC_ID,
    }
    return urllib.parse.urlencode(params)


def _parse_response(data: dict, limit: int) -> list[dict]:
    """Extract job dicts from the GraphQL response payload."""
    jobs: list[dict] = []

    # Navigate the typical response shape:
    # data -> job_search -> results -> edges -> node
    try:
        edges = (
            data.get("data", {})
            .get("job_search", {})
            .get("results", {})
            .get("edges", [])
        )
    except AttributeError:
        edges = []

    if not edges:
        # Alternate shape: data -> results -> edges
        try:
            edges = data.get("data", {}).get("results", {}).get("edges", [])
        except AttributeError:
            edges = []

    seen_ids: set[str] = set()

    for edge in edges:
        node = edge.get("node", {}) if isinstance(edge, dict) else {}
        if not node:
            continue

        job_id = str(node.get("id", "")).strip()
        title = (node.get("title") or "").strip()
        if not job_id or not title or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        # Locations is an array of objects or strings
        raw_locations: list = node.get("locations", []) or []
        location_parts: list[str] = []
        for loc in raw_locations:
            if isinstance(loc, dict):
                city = loc.get("city", "") or ""
                state = loc.get("state", "") or ""
                country = loc.get("country", "") or ""
                parts = [p for p in [city, state, country] if p]
                if parts:
                    location_parts.append(", ".join(parts))
            elif isinstance(loc, str) and loc:
                location_parts.append(loc)
        location = "; ".join(location_parts)

        remote = "remote" in (location + " " + title).lower()

        jobs.append({
            "external_id": f"meta_{job_id}",
            "title": title,
            "company_name": "Meta",
            "location": location,
            "remote": remote,
            "url": f"{_BASE_URL}/jobs/{job_id}",
            "description": "",
            "posted_at": None,
            "source": "meta",
            "ats": None,
        })

        if len(jobs) >= limit:
            break

    return jobs


async def search_meta_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Fetch Meta job listings via the internal careers GraphQL API.

    Parameters
    ----------
    search_text:
        Free-text query string.
    limit:
        Maximum number of jobs to return.

    Returns
    -------
    list[dict]
        Normalized job dicts, or empty list on any failure.
    """
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
        ) as client:
            # Step 1: get LSD token
            lsd_token = await _fetch_lsd_token(client)
            if not lsd_token:
                logger.debug("Meta: could not obtain LSD token, skipping")
                return []

            # Step 2: call GraphQL search
            body = _build_graphql_body(lsd_token, search_text)
            resp = await client.post(
                _GRAPHQL_URL,
                content=body.encode(),
                headers=_graphql_headers(lsd_token),
                timeout=20,
            )

            if resp.status_code != 200:
                logger.debug("Meta GraphQL returned %d", resp.status_code)
                return []

            # Strip JSONP/XSS prefix if present ("for (;;);")
            text = resp.text.lstrip()
            if text.startswith("for (;;);"):
                text = text[len("for (;;);"):]

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                logger.debug("Meta GraphQL non-JSON response")
                return []

    except Exception:
        logger.exception("Meta careers GraphQL request failed")
        return []

    jobs = _parse_response(data, limit)
    logger.info("Meta Careers: %d jobs (query=%r)", len(jobs), search_text)
    return jobs
