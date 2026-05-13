"""Best-effort client for Wellfound (formerly AngelList Talent) jobs.

**Production status: BEST-EFFORT / DEGRADED**

Wellfound serves a JS-heavy SPA with aggressive anti-bot detection.  In practice
this client returns zero results most of the time in production because the
server responds with a 403, a Cloudflare challenge, or a "Please enable JS"
page.  Other startup sources (YC Jobs, VentureLoop, Conviction, Speedrun) are
more reliable and provide richer metadata.

This client is retained so that *if* Wellfound becomes accessible (via a
sanctioned API, RSS feed, or relaxed bot policy) it will start contributing
again automatically.  It intentionally fails soft to ``[]`` and never blocks
or slows down the rest of the startup discover flow.

Decision documented: 2026-05-13 — keep as best-effort, do not invest in
browser-based workarounds (headless Chrome, Playwright) to bypass anti-bot.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.utils.startup_jobs import startup_tags, text_matches_query

logger = logging.getLogger(__name__)

BASE_URL = "https://wellfound.com/jobs"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Anti-bot indicator strings that signal the response is not real job data.
_ANTI_BOT_INDICATORS = (
    "Please enable JS",
    "disable any ad blocker",
    "Checking if the site connection is secure",
    "cf-browser-verification",
    "Just a moment...",
    "Attention Required!",
)


def parse_jobs_page_html(html_content: str, *, query: str | None = None, limit: int = 100) -> list[dict]:
    soup = BeautifulSoup(html_content or "", "html.parser")
    jobs: list[dict] = []

    for card in soup.select("[data-test='JobListItem'], .job-listing-item"):
        title_node = card.select_one("[data-test='job-title'], .job-title")
        company_node = card.select_one("[data-test='job-company'], .job-company")
        location_node = card.select_one("[data-test='job-location'], .job-location")
        link_node = card.select_one("a[href]")
        description_node = card.select_one("[data-test='job-snippet'], .job-snippet")
        time_node = card.select_one("time[datetime]")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        company_name = company_node.get_text(" ", strip=True) if company_node else ""
        location = location_node.get_text(" ", strip=True) if location_node else ""
        description = description_node.get_text(" ", strip=True) if description_node else ""
        job_url = link_node.get("href") if link_node else ""
        searchable_text = " ".join(part for part in [title, company_name, location, description] if part)
        if query and not text_matches_query(text=searchable_text, query=query):
            continue
        if not title or not company_name or not job_url:
            continue
        jobs.append({
            "external_id": f"wellfound_{job_url.rstrip('/').rsplit('/', 1)[-1]}",
            "title": title,
            "company_name": company_name,
            "location": location or None,
            "remote": "remote" in location.lower(),
            "url": urljoin(BASE_URL, job_url),
            "description": description or None,
            "posted_at": time_node.get("datetime") if time_node else None,
            "source": "wellfound",
            "tags": startup_tags("wellfound"),
        })
        if len(jobs) >= limit:
            break

    return jobs


async def search_wellfound_jobs(query: str | None = None, limit: int = 100) -> list[dict]:
    """Fetch Wellfound jobs, returning ``[]`` on any failure.

    This is intentionally best-effort.  Failures are logged at INFO level
    (not WARNING) because they are the expected outcome in production.
    """
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(BASE_URL, headers=REQUEST_HEADERS)
    except httpx.HTTPError as exc:
        logger.info(
            "Wellfound jobs fetch failed (best-effort source, expected in production)",
            extra={"error": str(exc)},
        )
        return []

    if response.status_code == 403:
        logger.info(
            "Wellfound returned 403 (anti-bot block, expected in production)",
        )
        return []

    if response.status_code != 200:
        logger.info(
            "Wellfound jobs unavailable: status=%s (best-effort source)",
            response.status_code,
        )
        return []

    if any(indicator in response.text for indicator in _ANTI_BOT_INDICATORS):
        logger.info(
            "Wellfound response contains anti-bot challenge (best-effort source)",
        )
        return []

    jobs = parse_jobs_page_html(response.text, query=query, limit=limit)
    if jobs:
        logger.info(
            "Wellfound returned %d jobs (rare success — anti-bot was not triggered)",
            len(jobs),
        )
    return jobs
