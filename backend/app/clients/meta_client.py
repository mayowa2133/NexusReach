"""Meta Careers job search client.

Meta's careers site (metacareers.com) requires JavaScript rendering and
returns a login wall for unauthenticated server-side requests.  This client
uses Crawl4AI (headless browser) to render the page and extract job data.

Best-effort: requires Crawl4AI (Playwright) to be installed.  Returns an
empty list if Crawl4AI is unavailable or Meta blocks the headless browser.
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.metacareers.com/jobs?q={query}"
_JOB_URL_PREFIX = "https://www.metacareers.com"

# Meta's rendered page contains job cards with links and titles.
_JOB_LINK_RE = re.compile(
    r'href="(/jobs/(\d+)/?)[^"]*"[^>]*>',
    re.IGNORECASE,
)
_TITLE_AFTER_LINK_RE = re.compile(
    r'href="/jobs/\d+/?[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{5,100})',
    re.IGNORECASE,
)
# Broader pattern for job card data
_JOB_CARD_RE = re.compile(
    r'"jobId"\s*:\s*"(\d+)".*?"title"\s*:\s*"([^"]+)"',
    re.DOTALL,
)
_LOCATION_IN_CARD_RE = re.compile(
    r'"location"\s*:\s*"([^"]+)"',
)


def _parse_jobs_from_html(html: str) -> list[dict]:
    """Extract job listings from rendered Meta careers HTML."""
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    # Strategy 1: Look for structured JSON data in the rendered page
    for match in _JOB_CARD_RE.finditer(html):
        job_id = match.group(1)
        title = match.group(2).strip()
        if not title or job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        # Try to find location near this job entry
        location = ""
        loc_match = _LOCATION_IN_CARD_RE.search(html[match.start():match.start() + 500])
        if loc_match:
            location = loc_match.group(1)

        jobs.append({
            "external_id": f"meta_{job_id}",
            "title": title,
            "company_name": "Meta",
            "location": location,
            "remote": "remote" in (location + " " + title).lower(),
            "url": f"{_JOB_URL_PREFIX}/jobs/{job_id}",
            "description": "",
            "posted_at": None,
            "source": "meta",
            "ats": None,
        })

    if jobs:
        return jobs

    # Strategy 2: Extract from DOM links with titles
    for match in _TITLE_AFTER_LINK_RE.finditer(html):
        full_text = match.group(0)
        job_id_match = re.search(r"/jobs/(\d+)", full_text)
        if not job_id_match:
            continue
        job_id = job_id_match.group(1)
        title = match.group(1).strip()

        if not title or job_id in seen_ids or len(title) < 5:
            continue
        seen_ids.add(job_id)

        jobs.append({
            "external_id": f"meta_{job_id}",
            "title": title,
            "company_name": "Meta",
            "location": "",
            "remote": "remote" in title.lower(),
            "url": f"{_JOB_URL_PREFIX}/jobs/{job_id}",
            "description": "",
            "posted_at": None,
            "source": "meta",
            "ats": None,
        })

    return jobs


async def search_meta_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Fetch Meta jobs by rendering their careers page with a headless browser.

    Requires Crawl4AI to be installed.  Returns an empty list if unavailable.
    """
    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore
    except ImportError:
        logger.debug("Meta client: Crawl4AI not installed, skipping")
        return []

    url = _SEARCH_URL.format(query=search_text or "software engineer")

    try:
        async with AsyncWebCrawler() as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url),
                timeout=30,
            )
    except asyncio.TimeoutError:
        logger.warning("Meta careers page timed out")
        return []
    except Exception:
        logger.exception("Meta careers headless fetch failed")
        return []

    if not getattr(result, "success", False):
        logger.debug("Meta Crawl4AI result unsuccessful")
        return []

    html = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
    if not html:
        logger.debug("Meta: empty HTML from Crawl4AI")
        return []

    jobs = _parse_jobs_from_html(html)[:limit]
    logger.info("Meta Careers: %d jobs (query=%r)", len(jobs), search_text)
    return jobs
