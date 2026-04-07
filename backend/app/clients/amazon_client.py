"""Amazon Jobs search client.

Amazon exposes a public JSON search API at:

    GET https://www.amazon.jobs/en/search.json

This client queries that API to discover Amazon job postings.
"""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

_BASE_URL = "https://www.amazon.jobs"


def _parse_posted_date(raw: str) -> str | None:
    """Convert Amazon date strings like 'January 9, 2026' to ISO 8601."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw.strip(), "%B %d, %Y")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        logger.debug("Could not parse Amazon posted_date: %r", raw)
        return None


async def search_amazon_jobs(
    search_text: str = "",
    limit: int = 20,
    category: str | None = None,
) -> list[dict]:
    """Fetch jobs from the Amazon Jobs search API.

    Args:
        search_text: Free-text keyword search.
        limit: Maximum number of jobs to return (API max per request is 100).
        category: Optional job category filter (passed as ``category[]``).

    Returns:
        List of normalized job dicts ready for the NexusReach job pipeline.
    """
    params: dict[str, str | int] = {
        "result_limit": min(limit, 100),
        "offset": 0,
        "sort": "recent",
    }
    if search_text:
        params["keyword"] = search_text
    if category:
        params["category[]"] = category

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                f"{_BASE_URL}/en/search.json",
                params=params,
                headers=_HEADERS,
            )
            if resp.status_code != 200:
                logger.warning("Amazon Jobs returned %d", resp.status_code)
                return []

        data = resp.json()

        if data.get("error"):
            logger.warning("Amazon Jobs API error: %s", data["error"])
            return []

        raw_jobs = data.get("jobs", [])
        total_hits = data.get("hits", 0)
    except Exception:
        logger.exception("Amazon Jobs fetch failed")
        return []

    jobs: list[dict] = []
    for j in raw_jobs:
        title = j.get("title", "")
        if not title:
            continue

        job_path = j.get("job_path", "")
        job_url = f"{_BASE_URL}{job_path}" if job_path else ""

        location_parts = [
            p for p in (j.get("city"), j.get("state"), j.get("country_code")) if p
        ]
        location = j.get("normalized_location") or j.get("location") or ", ".join(location_parts)

        description_parts = [
            j.get("description", ""),
            j.get("basic_qualifications", ""),
            j.get("preferred_qualifications", ""),
        ]
        description = "\n\n".join(p for p in description_parts if p)

        remote = "remote" in (location + " " + title).lower()
        posted_at = _parse_posted_date(j.get("posted_date", ""))

        external_id = j.get("id_icims") or j.get("id") or ""

        jobs.append({
            "external_id": str(external_id),
            "title": title,
            "company_name": "Amazon",
            "location": location,
            "remote": remote,
            "url": job_url,
            "description": description,
            "posted_at": posted_at,
            "source": "amazon",
            "ats": None,
        })

        if len(jobs) >= limit:
            break

    logger.info("Amazon Jobs: %d jobs (of %d hits)", len(jobs), total_hits)
    return jobs
