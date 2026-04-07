"""Tesla Careers job search client.

Tesla's careers site (tesla.com/careers/search) is protected by Akamai Bot
Manager which blocks standard HTTP requests.  This client uses Crawl4AI
(headless browser) to render the page and extract job data from the DOM.

Best-effort: requires Crawl4AI (Playwright) to be installed.  Returns an
empty list if Crawl4AI is unavailable or Tesla blocks the headless browser.
"""

from __future__ import annotations

import asyncio
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
    """Fetch Tesla jobs by rendering their careers page with a headless browser.

    Requires Crawl4AI to be installed.  Returns an empty list if unavailable.
    """
    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore
    except ImportError:
        logger.debug("Tesla client: Crawl4AI not installed, skipping")
        return []

    url = _SEARCH_URL.format(query=search_text or "software")

    try:
        async with AsyncWebCrawler() as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url),
                timeout=30,
            )
    except asyncio.TimeoutError:
        logger.warning("Tesla careers page timed out")
        return []
    except Exception:
        logger.exception("Tesla careers headless fetch failed")
        return []

    if not getattr(result, "success", False):
        logger.debug("Tesla Crawl4AI result unsuccessful")
        return []

    html = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
    if not html:
        logger.debug("Tesla: empty HTML from Crawl4AI")
        return []

    jobs = _parse_jobs_from_html(html)[:limit]
    logger.info("Tesla Careers: %d jobs (query=%r)", len(jobs), search_text)
    return jobs
