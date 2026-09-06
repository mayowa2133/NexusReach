"""Tesla Careers parser; remote browser retrieval is disabled in production."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.tesla.com/careers/search/?query={query}&site=US"
_JOB_URL_PREFIX = "https://www.tesla.com"

# Patterns to extract job data from rendered HTML
_JOB_LINK_RE = re.compile(
    r'href="(/careers/search/job/[^"]+)"[^>]*>([^<]+)',
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r'<span[^>]*class="[^"]*location[^"]*"[^>]*>([^<]+)',
    re.IGNORECASE,
)


def _extract_job_id(path: str) -> str:
    """Extract a job ID from a Tesla careers path like /careers/search/job/software-123456."""
    parts = path.rstrip("/").split("-")
    # The numeric ID is typically the last segment
    for part in reversed(parts):
        if part.isdigit():
            return part
    # Fallback: use the slug
    return path.rstrip("/").rsplit("/", 1)[-1]


def _parse_jobs_from_html(html: str) -> list[dict]:
    """Parse job listings from rendered Tesla careers HTML."""
    jobs: list[dict] = []
    seen: set[str] = set()

    for match in _JOB_LINK_RE.finditer(html):
        path = match.group(1)
        title = match.group(2).strip()

        if not title or path in seen:
            continue
        seen.add(path)

        job_id = _extract_job_id(path)
        job_url = f"{_JOB_URL_PREFIX}{path}"

        jobs.append({
            "external_id": f"tesla_{job_id}",
            "title": title,
            "company_name": "Tesla",
            "location": "",
            "remote": "remote" in title.lower(),
            "url": job_url,
            "apply_url": job_url,
            "description": "",
            "posted_at": None,
            "source": "tesla",
            "ats": None,
        })

    return jobs


async def search_tesla_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Return a controlled unavailable result without an unbounded browser."""
    logger.info("Tesla rendered discovery is unavailable in the hardened runtime")
    return []
