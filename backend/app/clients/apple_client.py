"""Apple Jobs board-level search client.

Apple's careers site exposes an internal JSON search API at:

    POST https://jobs.apple.com/api/role/search

This client queries that API to bulk-discover Apple job postings.

Best-effort: the API may require browser cookies or specific session
headers that are not sent here.  If Apple starts gating the endpoint
behind a cookie wall or CAPTCHA, this client will gracefully return an
empty list rather than crash.
"""

import logging
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    """Turn a job title into a URL-safe slug matching Apple's URL pattern."""
    return _SLUG_RE.sub("-", title.lower()).strip("-")


def _join_locations(locations: list[dict]) -> str:
    """Join an array of Apple location objects into a semicolon-separated string."""
    names: list[str] = []
    for loc in locations:
        name = loc.get("name") or loc.get("city") or ""
        if name and name not in names:
            names.append(name)
    return "; ".join(names)


def _is_remote(locations_text: str, title: str) -> bool:
    """Heuristic check for remote roles based on location and title text."""
    combined = (locations_text + " " + title).lower()
    return "remote" in combined


def _parse_date(raw: str | None) -> str | None:
    """Parse an ISO-ish date string into a clean ISO 8601 timestamp.

    Apple may return dates like "2026-04-01T00:00:00.000Z" or plain
    date strings like "2026-04-01".  Returns None if unparseable.
    """
    if not raw:
        return None

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue

    return None


async def search_apple_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Fetch jobs from Apple's internal careers search API.

    Parameters
    ----------
    search_text:
        Free-text query string.  Empty string returns default/featured results.
    limit:
        Maximum number of normalized job dicts to return.

    Returns
    -------
    list[dict]
        Each dict has keys: external_id, title, company_name, location, remote,
        url, description, posted_at, source, ats, department.
    """
    url = "https://jobs.apple.com/api/role/search"
    body: dict = {
        "query": search_text,
        "page": 1,
        "locale": "en-us",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(url, json=body, headers=_HEADERS)
            if resp.status_code != 200:
                logger.debug("Apple Jobs %d for query=%r", resp.status_code, search_text)
                return []

        data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Apple Jobs request failed: %s", exc)
        return []
    except Exception:
        logger.exception("Apple Jobs unexpected error")
        return []

    results = data.get("searchResults", [])

    jobs: list[dict] = []
    for item in results:
        position_id = str(item.get("positionId") or item.get("id") or "")
        title = item.get("postingTitle") or item.get("transformedPostingTitle") or ""
        if not title or not position_id:
            continue

        locations_raw = item.get("locations") or []
        locations_text = _join_locations(locations_raw)

        posted_raw = item.get("postDateInGMT") or item.get("postingDate")
        posted_at = _parse_date(posted_raw)

        team = item.get("team") or {}
        department = team.get("teamName") or ""

        slug = _slugify(title)
        job_url = f"https://jobs.apple.com/en-us/details/{position_id}/{slug}"

        jobs.append({
            "external_id": f"apple_{position_id}",
            "title": title,
            "company_name": "Apple",
            "location": locations_text,
            "remote": _is_remote(locations_text, title),
            "url": job_url,
            "description": "",
            "posted_at": posted_at,
            "source": "apple",
            "ats": None,
            "department": department,
        })

        if len(jobs) >= limit:
            break

    logger.info(
        "Apple Jobs: %d jobs returned (query=%r, total_results=%d)",
        len(jobs),
        search_text,
        len(results),
    )
    return jobs
