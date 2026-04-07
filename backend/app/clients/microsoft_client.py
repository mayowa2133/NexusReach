"""Microsoft Careers job search client.

Microsoft's careers site at jobs.careers.microsoft.com exposes a semi-public
search API used by their frontend JS.  The primary endpoint is:

    POST https://gcsservices.careers.microsoft.com/search/api/v1/search

This client sends the same JSON payload format the browser sends and parses
the response into the common job dict format used across NexusReach.

This is best-effort: Microsoft may enforce rate limits, require specific
headers, or change the API shape without notice.  On any failure the client
falls back gracefully to an empty list so callers never need to handle
exceptions from this module.
"""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Origin": "https://jobs.careers.microsoft.com",
    "Referer": "https://jobs.careers.microsoft.com/",
}

_SEARCH_URL = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
_JOB_URL_TEMPLATE = "https://jobs.careers.microsoft.com/global/en/job/{job_id}"


def _parse_date(raw: str | None) -> str | None:
    """Parse Microsoft date strings into ISO 8601.

    Known formats include ISO 8601 timestamps with or without timezone info
    and plain date strings like "2026-03-15".
    """
    if not raw:
        return None

    # Already ISO 8601 with timezone
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue

    logger.debug("Microsoft: could not parse date %r", raw)
    return None


def _extract_location(job: dict) -> str:
    """Build a human-readable location string from the API response."""
    # The API nests location data in different ways; try the most common shapes.
    locations = job.get("locations") or job.get("properties", {}).get("locations") or []

    if isinstance(locations, list):
        parts: list[str] = []
        for loc in locations:
            if isinstance(loc, str):
                parts.append(loc)
            elif isinstance(loc, dict):
                parts.append(loc.get("displayName") or loc.get("name") or "")
        text = "; ".join(p for p in parts if p)
        if text:
            return text

    # Fallback: flat location field
    return job.get("location", "") or job.get("primaryLocation", "") or ""


def _is_remote(job: dict, location: str) -> bool:
    """Determine whether a posting is remote from available signals."""
    combined = (location + " " + (job.get("title") or "")).lower()
    if "remote" in combined:
        return True

    work_mode = (
        job.get("properties", {}).get("workSiteFlexibility")
        or job.get("workSiteFlexibility")
        or ""
    )
    if isinstance(work_mode, str) and "remote" in work_mode.lower():
        return True

    return False


async def search_microsoft_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Search Microsoft Careers and return normalized job dicts.

    Returns an empty list on any error so callers can treat this as
    best-effort without extra error handling.
    """
    body: dict = {
        "QueryString": search_text or "",
        "PageSize": min(limit, 20),
        "Page": 1,
        "Filters": [],
        "OrderBy": "Relevance",
        "Fields": [
            "title",
            "description",
            "locations",
            "datePosted",
            "jobId",
            "properties",
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(_SEARCH_URL, json=body, headers=_HEADERS)

            if resp.status_code != 200:
                logger.debug(
                    "Microsoft search API returned %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return []

            data = resp.json()
    except httpx.HTTPError as exc:
        logger.debug("Microsoft search HTTP error: %s", exc)
        return []
    except Exception:
        logger.exception("Microsoft search unexpected error")
        return []

    # The API wraps results in different keys depending on version.
    postings: list[dict] = (
        data.get("operationResult", {}).get("result", {}).get("jobs")
        or data.get("jobs")
        or data.get("results")
        or data.get("operationResult", {}).get("result", {}).get("results")
        or []
    )

    jobs: list[dict] = []
    for p in postings:
        title = p.get("title") or ""
        if not title:
            continue

        job_id = str(p.get("jobId") or p.get("id") or "")
        location = _extract_location(p)
        posted_at = _parse_date(
            p.get("datePosted")
            or p.get("postingDate")
            or p.get("properties", {}).get("datePosted")
        )

        description = (
            p.get("description")
            or p.get("properties", {}).get("description")
            or ""
        )

        job_url = _JOB_URL_TEMPLATE.format(job_id=job_id) if job_id else ""

        jobs.append({
            "external_id": f"ms_{job_id}" if job_id else "",
            "title": title,
            "company_name": "Microsoft",
            "location": location,
            "remote": _is_remote(p, location),
            "url": job_url,
            "description": description,
            "posted_at": posted_at,
            "source": "microsoft",
            "ats": None,
        })

        if len(jobs) >= limit:
            break

    logger.info(
        "Microsoft Careers: %d jobs returned (limit %d)",
        len(jobs),
        limit,
    )
    return jobs
