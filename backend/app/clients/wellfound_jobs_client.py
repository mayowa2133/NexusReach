"""Best-effort client for Wellfound jobs."""

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
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(BASE_URL, headers=REQUEST_HEADERS)
    except httpx.HTTPError:
        logger.warning("Wellfound jobs fetch failed")
        return []

    if response.status_code != 200:
        logger.warning("Wellfound jobs unavailable: status=%s", response.status_code)
        return []

    if "Please enable JS" in response.text or "disable any ad blocker" in response.text:
        logger.warning("Wellfound jobs blocked by anti-bot challenge")
        return []

    return parse_jobs_page_html(response.text, query=query, limit=limit)
