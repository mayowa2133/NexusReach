"""Google Careers job search client.

Google's careers page at google.com/about/careers embeds job listings in
server-rendered ``AF_initDataCallback`` chunks.  The ``ds:1`` chunk contains
an array of job entries with full metadata: title, ID, description,
qualifications, company, locations, and apply URL.

This client fetches the results HTML page and parses the embedded data.
No authentication is required — the data is part of the initial HTML
payload returned to any browser-like GET request.
"""

from __future__ import annotations

import logging
import re
from html import unescape

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_BASE_URL = "https://www.google.com/about/careers/applications/jobs/results"
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Regex to extract the job array from the ds:1 AF_initDataCallback chunk.
# The data key looks like: AF_initDataCallback({key: 'ds:1', hash: '2', data:[[...]], sideChannel: {}})
_DS1_RE = re.compile(
    r"AF_initDataCallback\(\{key:\s*'ds:1'.*?data:(\[\[.*?\]\])\s*,\s*sideChannel",
    re.DOTALL,
)

# Each job in ds:1 is an array element starting with [<id>, <title>, <apply_url>, ...]
_JOB_RE = re.compile(
    r'\["(\d{10,})","((?:[^"\\]|\\.)*)","(https://www\.google\.com/about/careers/applications/signin\?[^"]*)"',
)

# Location pattern: ["City, State, Country", [...], "City", null, "State", "CountryCode"]
_LOC_RE = re.compile(r'\["([^"]+,\s*[A-Z]{2},\s*[A-Z]{2,})",\["')


def _strip_tags(html: str) -> str:
    return _WHITESPACE_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()


def _extract_job_url(raw_apply_url: str, job_id: str) -> str:
    """Build a clean job detail URL from the raw apply URL."""
    return f"https://www.google.com/about/careers/applications/jobs/results/{job_id}"


async def search_google_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Fetch jobs from Google Careers by parsing server-rendered HTML.

    Parameters
    ----------
    search_text:
        Free-text query (e.g. ``"software engineer"``).
    limit:
        Maximum jobs to return.  Google renders ~20 per page.

    Returns
    -------
    list[dict]
        Normalized job dicts for the NexusReach pipeline.
    """
    params: dict[str, str | int] = {"page": 1}
    if search_text:
        params["q"] = search_text

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(_BASE_URL, params=params, headers=_HEADERS)
            if resp.status_code != 200:
                logger.debug("Google Careers returned %d", resp.status_code)
                return []
            html = resp.text
    except Exception:
        logger.exception("Google Careers fetch failed")
        return []

    # Parse job entries from the embedded data
    job_entries = _JOB_RE.findall(html)
    if not job_entries:
        logger.info("Google Careers: no jobs found for query=%r", search_text)
        return []

    # Build a mapping of job_id → locations by scanning location patterns
    # near each job entry.  We do a simpler approach: extract all locations
    # in order and pair them with jobs positionally.
    all_locations = _LOC_RE.findall(html)

    jobs: list[dict] = []
    for idx, (job_id, title, apply_url) in enumerate(job_entries):
        title = title.replace("\\u003c", "<").replace("\\u003e", ">")
        title = _strip_tags(title)
        if not title:
            continue

        location = all_locations[idx] if idx < len(all_locations) else ""
        remote = "remote" in (location + " " + title).lower()
        job_url = _extract_job_url(apply_url, job_id)

        # Extract company from the data (field after qualifications, before locale)
        # Default to "Google" since the vast majority are Google proper
        company = "Google"

        jobs.append({
            "external_id": f"goog_{job_id}",
            "title": title,
            "company_name": company,
            "location": location,
            "remote": remote,
            "url": job_url,
            "description": "",
            "posted_at": None,
            "source": "google_careers",
            "ats": None,
        })

        if len(jobs) >= limit:
            break

    logger.info("Google Careers: %d jobs (query=%r)", len(jobs), search_text)
    return jobs
