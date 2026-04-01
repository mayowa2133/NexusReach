"""Lever job board scraper — scrapes jobs.lever.co HTML pages.

The Lever public JSON API (api.lever.co/v0/postings/) is deprecated for
most companies.  However jobs.lever.co/{company} HTML pages still render
for active Lever customers, and contain structured .posting elements.
"""

import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def search_lever_html(company_slug: str, limit: int = 50) -> list[dict]:
    """Scrape open jobs from a Lever company board page."""
    url = f"https://jobs.lever.co/{company_slug}"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "NexusReach/1.0"})
        if resp.status_code != 200:
            logger.debug("Lever HTML %d for %s", resp.status_code, company_slug)
            return []

    soup = BeautifulSoup(resp.text, "html.parser")
    postings = soup.select(".posting")

    if not postings:
        logger.debug("No .posting elements found for %s", company_slug)
        return []

    # Try to get the company name from the page
    company_name = company_slug
    brand_el = soup.select_one(".main-header-logo img")
    if brand_el and brand_el.get("alt"):
        company_name = brand_el["alt"].replace(" logo", "").replace(" Logo", "").strip() or company_slug

    jobs: list[dict] = []
    seen: set[str] = set()

    for posting in postings:
        link_el = posting.select_one("a.posting-title")
        if not link_el:
            continue

        href = link_el.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)

        title_el = link_el.select_one("h5")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            continue

        location_el = posting.select_one(".posting-categories .sort-by-location")
        location = location_el.get_text(strip=True) if location_el else ""

        dept_el = posting.select_one(".posting-categories .sort-by-team")
        department = dept_el.get_text(strip=True) if dept_el else ""

        commitment_el = posting.select_one(".posting-categories .sort-by-commitment")
        employment_type = commitment_el.get_text(strip=True) if commitment_el else ""

        # Extract external ID from URL like /spotify/3ada366b-...
        ext_id_match = re.search(r"/([0-9a-f-]{36})$", href)
        external_id = f"lv_{ext_id_match.group(1)}" if ext_id_match else f"lv_{href.split('/')[-1]}"

        jobs.append({
            "external_id": external_id,
            "title": title,
            "company_name": company_name,
            "location": location,
            "remote": "remote" in location.lower(),
            "url": href,
            "description": "",
            "department": department,
            "employment_type": employment_type.lower() if employment_type else "",
            "posted_at": "",
            "source": "lever",
            "ats": "lever",
            "ats_slug": company_slug,
        })

        if len(jobs) >= limit:
            break

    logger.info("Lever HTML scraped %d jobs from %s", len(jobs), company_slug)
    return jobs
