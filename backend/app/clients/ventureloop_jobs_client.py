"""Client for VentureLoop startup jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.utils.startup_jobs import startup_tags, text_matches_query

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ventureloop.com/ventureloop/"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
PUBLIC_SEARCH_PATHS = [
    "job_search_results.php?pageno=1&btn=1&jcat=12&dc=all&ldata=San%24%24Francisco%2C%24%24CA%2C%24%24US&jt=1&jc=1&jd=1&d=100",
    "job_search_results.php?pageno=1&btn=1&jcat=12&dc=all&ldata=New%24%24York%2C%24%24NY%2C%24%24US&jt=1&jc=1&jd=1&d=100",
    "job_search_results.php?pageno=1&btn=1&jcat=12&dc=all&ldata=Austin%24%24Texas%2C%24%24TX%2C%24%24US&jt=1&jc=1&jd=1&d=100",
]


def _parse_posted_at(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    try:
        dt = datetime.strptime(raw_value.strip(), "%m-%d-%Y")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _normalize_location(cell) -> str | None:
    values = [line.strip() for line in cell.stripped_strings if line.strip()]
    if not values:
        return None
    unique_values = list(dict.fromkeys(values))
    return " | ".join(unique_values)


def _external_id_for_href(href: str) -> str | None:
    parsed = urlparse(urljoin(BASE_URL, href))
    job_id = (parse_qs(parsed.query).get("jobid") or [None])[0]
    return f"ventureloop_{job_id}" if job_id else None


def parse_jobs_page_html(html_content: str, *, query: str | None = None, limit: int = 200) -> list[dict]:
    soup = BeautifulSoup(html_content or "", "html.parser")
    table = soup.select_one("#news_tbl")
    if table is None:
        return []

    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for row in table.select("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        link = cells[1].find("a", href=True)
        if link is None:
            continue

        title = link.get_text(" ", strip=True)
        company_name = cells[2].get_text(" ", strip=True)
        vc_name = cells[3].get_text(" ", strip=True)
        location = _normalize_location(cells[4])
        searchable_text = " ".join(part for part in [title, company_name, location or "", vc_name] if part)
        if query and not text_matches_query(text=searchable_text, query=query):
            continue

        external_id = _external_id_for_href(link["href"])
        if not external_id or external_id in seen_ids:
            continue
        seen_ids.add(external_id)

        jobs.append({
            "external_id": external_id,
            "title": title,
            "company_name": company_name,
            "location": location,
            "remote": "remote" in (location or "").lower(),
            "url": urljoin(BASE_URL, link["href"]),
            "description": f"Backed by {vc_name}" if vc_name else None,
            "posted_at": _parse_posted_at(cells[0].get_text(" ", strip=True)),
            "source": "ventureloop",
            "tags": startup_tags("ventureloop"),
        })
        if len(jobs) >= limit:
            break

    return jobs


async def search_ventureloop_jobs(query: str | None = None, limit: int = 200) -> list[dict]:
    jobs: list[dict] = []
    seen_ids: set[str] = set()
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for path in PUBLIC_SEARCH_PATHS:
            response = await client.get(urljoin(BASE_URL, path), headers=REQUEST_HEADERS)
            if response.status_code != 200:
                logger.warning("VentureLoop fetch failed for %s: %s", path, response.status_code)
                continue
            for job in parse_jobs_page_html(response.text, query=query, limit=limit):
                external_id = str(job.get("external_id") or "")
                if external_id in seen_ids:
                    continue
                seen_ids.add(external_id)
                jobs.append(job)
                if len(jobs) >= limit:
                    return jobs
    return jobs
