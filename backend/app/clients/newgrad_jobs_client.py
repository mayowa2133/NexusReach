"""Client for newgrad-jobs.com — scrapes server-rendered job listings."""

import logging
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.newgrad-jobs.com"

# Categories that map to the site's URL structure (/list-{category})
CATEGORIES = [
    "software-engineer-jobs",
    "data-analyst",
    "cyber-security",
    "remote",
]


def _try_parse_date(text: str) -> str:
    """Try to parse a date string, return ISO string or empty."""
    try:
        dt = datetime.strptime(text.strip(), "%B %d, %Y")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, AttributeError):
        return ""


def _parse_salary(text: str) -> tuple[float | None, float | None, str]:
    """Extract salary range from text like '$115K/yr - $180K/yr'."""
    matches = re.findall(r"\$(\d+)K", text)
    if len(matches) >= 2:
        return float(matches[0]) * 1000, float(matches[1]) * 1000, "USD"
    if len(matches) == 1:
        return float(matches[0]) * 1000, None, "USD"
    return None, None, "USD"


async def fetch_job_list(
    category: str = "software-engineer-jobs",
    limit: int = 50,
) -> list[dict]:
    """Fetch job listings from a newgrad-jobs.com category page.

    Returns normalized job dicts ready for NexusReach ingestion.
    """
    url = f"{BASE_URL}/list-{category}"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "NexusReach/1.0"})
        if resp.status_code != 200:
            logger.warning("newgrad-jobs returned %d for %s", resp.status_code, url)
            return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Each job has two <a> tags with the same href:
    #   1. A logo-only link (class="w-inline-block", no text)
    #   2. A text link (class="flex-block-27 w-inline-block") containing:
    #      - p.jobtitle: job title
    #      - p.jobtime: date like "March 31, 2026"
    #      - p.companyname_list: company name
    # We target the text links by looking for stripped_strings.
    link_prefix = f"/list-{category}/"
    job_links = [
        a for a in soup.find_all("a", href=True)
        if a["href"].startswith(link_prefix) and list(a.stripped_strings)
    ]

    jobs: list[dict] = []
    seen_slugs: set[str] = set()

    for link in job_links:
        href = link["href"]
        slug = href[len(link_prefix):]
        if slug in seen_slugs or not slug:
            continue
        seen_slugs.add(slug)

        # Extract structured fields using CSS classes when available
        title_el = link.select_one("p.jobtitle, .jobtitle")
        date_el = link.select_one("p.jobtime, .jobtime")
        company_el = link.select_one("p.companyname_list, .companyname_list")

        title = title_el.get_text(strip=True) if title_el else ""
        posted_at = _try_parse_date(date_el.get_text(strip=True)) if date_el else ""
        company = company_el.get_text(strip=True) if company_el else ""

        # Fallback to positional parsing if CSS selectors miss
        if not title:
            text_parts = [t.strip() for t in link.stripped_strings]
            for part in text_parts:
                parsed_date = _try_parse_date(part)
                if parsed_date:
                    posted_at = posted_at or parsed_date
                elif not title:
                    title = part
                elif not company:
                    company = part

        if not title:
            continue

        jobs.append({
            "external_id": f"newgrad_{slug}",
            "title": title,
            "company_name": company,
            "location": "",
            "remote": category == "remote",
            "url": f"{BASE_URL}{href}",
            "description": "",
            "posted_at": posted_at,
            "source": "newgrad_jobs",
        })

        if len(jobs) >= limit:
            break

    return jobs


async def fetch_job_detail(job_url: str) -> dict | None:
    """Fetch additional details from an individual job page.

    Enriches with location, salary, and description.
    """
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(job_url, headers={"User-Agent": "NexusReach/1.0"})
        if resp.status_code != 200:
            return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Try to extract location
    location = ""
    loc_match = re.search(r"(?:Location|location)[:\s]+([^,\n]+(?:,\s*[^,\n]+)?)", text)
    if loc_match:
        location = loc_match.group(1).strip()

    # Try to extract salary
    salary_min, salary_max, currency = None, None, "USD"
    salary_match = re.search(r"\$\d+K/yr\s*-\s*\$\d+K/yr", text)
    if salary_match:
        salary_min, salary_max, currency = _parse_salary(salary_match.group(0))

    return {
        "location": location,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": currency,
    }


async def search_newgrad_jobs(
    query: str | None = None,
    category: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search newgrad-jobs.com for jobs across multiple categories.

    If a specific category is given, only that category is scraped.
    Otherwise, all known categories are scraped for maximum coverage.
    If a query is provided, results are filtered client-side by title/company match.
    """
    categories_to_search = [category] if category else CATEGORIES

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for cat in categories_to_search:
        per_cat_limit = limit * 2 if query else limit
        jobs = await fetch_job_list(category=cat, limit=per_cat_limit)
        for job in jobs:
            eid = job["external_id"]
            if eid not in seen_ids:
                seen_ids.add(eid)
                all_jobs.append(job)

    if query:
        keywords = query.lower().split()
        filtered = [
            j for j in all_jobs
            if any(
                kw in j["title"].lower() or kw in j.get("company_name", "").lower()
                for kw in keywords
            )
        ]
        return filtered[:limit]

    return all_jobs[:limit]
