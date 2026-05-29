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
from urllib.parse import urljoin

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

_SEARCH_URL = "https://apply.careers.microsoft.com/api/pcsx/search"
_JOB_URL_TEMPLATE = "https://apply.careers.microsoft.com{path}"


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


def _epoch_seconds_to_iso(raw: object) -> str | None:
    if not isinstance(raw, (int, float)) or raw <= 0:
        return None
    try:
        return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
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


def _work_mode(job: dict, location: str) -> str | None:
    raw = (
        job.get("properties", {}).get("workSiteFlexibility")
        or job.get("workSiteFlexibility")
        or ""
    )
    lowered = f"{raw} {location} {job.get('title') or ''}".lower()
    if "hybrid" in lowered:
        return "hybrid"
    if "remote" in lowered:
        return "remote"
    if "onsite" in lowered or "on-site" in lowered or "on site" in lowered:
        return "onsite"
    return None


def _work_mode_from_position(position: dict, location: str) -> str | None:
    raw = str(position.get("workLocationOption") or position.get("locationFlexibility") or "").lower()
    combined = f"{raw} {location} {position.get('name') or ''}".lower()
    if "hybrid" in combined:
        return "hybrid"
    if "remote" in combined:
        return "remote"
    if "onsite" in combined or "on-site" in combined or "on site" in combined:
        return "onsite"
    return None


async def search_microsoft_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Search Microsoft Careers and return normalized job dicts.

    Returns an empty list on any error so callers can treat this as
    best-effort without extra error handling.
    """
    params: dict = {
        "domain": "microsoft.com",
        "query": search_text or "",
        "location": "",
        "start": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                _SEARCH_URL,
                params=params,
                headers={
                    **_HEADERS,
                    "X-EF-NS": "pcsx",
                    "X-EF-REQ-ENDPOINT": "get_position_search_data",
                    "Referer": "https://apply.careers.microsoft.com/careers",
                },
            )

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

    postings: list[dict] = data.get("data", {}).get("positions") or []

    jobs: list[dict] = []
    for p in postings:
        title = p.get("name") or p.get("title") or ""
        if not title:
            continue

        job_id = str(p.get("displayJobId") or p.get("atsJobId") or p.get("id") or "")
        locations = p.get("standardizedLocations") or p.get("locations") or []
        location = "; ".join(str(loc) for loc in locations if loc) if isinstance(locations, list) else _extract_location(p)
        posted_at = _parse_date(
            p.get("datePosted")
            or p.get("postingDate")
            or p.get("properties", {}).get("datePosted")
        ) or _epoch_seconds_to_iso(p.get("postedTs") or p.get("creationTs"))

        description = (
            p.get("description")
            or p.get("properties", {}).get("description")
            or p.get("department")
            or ""
        )

        position_path = p.get("positionUrl") or ""
        job_url = _JOB_URL_TEMPLATE.format(path=position_path) if position_path else ""
        if job_url:
            job_url = urljoin("https://apply.careers.microsoft.com", job_url)
        work_mode = _work_mode_from_position(p, location)

        jobs.append({
            "external_id": f"ms_{job_id}" if job_id else "",
            "title": title,
            "company_name": "Microsoft",
            "location": location,
            "remote": work_mode == "remote" or _is_remote(p, location),
            "work_mode": work_mode or _work_mode(p, location),
            "url": job_url,
            "apply_url": job_url or None,
            "description": description,
            "posted_at": posted_at,
            "source": "microsoft",
            "ats": None,
            "department": p.get("department"),
        })

        if len(jobs) >= limit:
            break

    logger.info(
        "Microsoft Careers: %d jobs returned (limit %d)",
        len(jobs),
        limit,
    )
    return jobs
