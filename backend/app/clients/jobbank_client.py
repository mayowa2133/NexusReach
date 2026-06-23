"""Job Bank Canada (jobbank.gc.ca) — Canada's national employment board.

Job Bank has no public JSON search API (only employer XML feeds and a monthly
open-data CSV that omits posting URLs), so this client scrapes the public
job-search results page. It is **best-effort and fails soft to ``[]``** — the
same posture as the newgrad/Wellfound scrapers — so Job Bank being slow, blocked,
or changing its markup never breaks discovery for the other sources.

Job Bank is Canada-only, so callers should pass a Canadian ``location`` (or rely
on the discovery layer, which only invokes this source for Canadian seeds).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE = "https://www.jobbank.gc.ca"
_SEARCH_URL = _BASE + "/jobsearch/jobsearch"
_RESULTS_PER_PAGE = 25
_MAX_PAGES = 4  # bound the scrape: 4 pages * 25 = 100 results max
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}

# "Burnaby (BC)" / "Toronto (ON)" -> normalize the province to a clean suffix so
# the location geocodes to Canada and the Country=Canada filter catches it.
_PROVINCE_RE = re.compile(r"\s*\(([A-Z]{2})\)\s*$")


def _clean_location(raw: str | None) -> str:
    """Turn Job Bank's "City (PROV)" into "City, PROV, Canada"."""
    text = (raw or "").strip()
    if not text:
        return "Canada"
    m = _PROVINCE_RE.search(text)
    if m:
        city = _PROVINCE_RE.sub("", text).strip()
        return f"{city}, {m.group(1)}, Canada"
    if "canada" not in text.lower():
        return f"{text}, Canada"
    return text


def _parse_posted_at(raw: str | None) -> str | None:
    """"June 09, 2026" -> ISO date "2026-06-09" so posted_date populates."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def _li_text(article, cls: str) -> str:
    """Text of an ``li.<cls>`` with the screen-reader label span stripped."""
    li = article.find("li", class_=cls)
    if not li:
        return ""
    for inv in li.find_all("span", class_="wb-inv"):
        inv.extract()
    text = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
    # Some cards carry a visible label prefix ("Salary $52.40 hourly").
    return re.sub(r"^(Salary|Location)\s+", "", text).strip()


def _parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[dict] = []
    for art in soup.find_all("article", id=re.compile(r"^article-\d+")):
        job_id = art.get("id", "").replace("article-", "").strip()
        if not job_id:
            continue
        noc = art.find("span", class_="noctitle")
        title = noc.get_text(strip=True) if noc else ""
        if not title:
            continue

        telework = art.find("span", class_="telework")
        telework_txt = (telework.get_text(strip=True) if telework else "").lower()
        is_remote = "remote" in telework_txt or "telework" in telework_txt
        if is_remote:
            work_mode = "remote"
        elif "hybrid" in telework_txt:
            work_mode = "hybrid"
        else:
            work_mode = "onsite"

        salary = _li_text(art, "salary")
        url = f"{_BASE}/jobsearch/jobposting/{job_id}"
        jobs.append(
            {
                "external_id": f"jobbank_{job_id}",
                "title": title,
                "company_name": _li_text(art, "business"),
                "location": _clean_location(_li_text(art, "location")),
                "remote": is_remote,
                "work_mode": work_mode,
                "url": url,
                "apply_url": url,
                "description": "",
                "employment_type": "",
                "posted_at": _parse_posted_at(_li_text(art, "date")),
                "salary": salary,
                "tags": [],
                "source": "jobbank",
            }
        )
    return jobs


async def search_jobbank(
    query: str,
    location: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search Job Bank Canada. Best-effort; fails soft to ``[]``.

    Args:
        query: free-text job query (e.g. "software developer").
        location: Canadian location string (e.g. "Toronto, ON"). Optional —
            Job Bank searches all of Canada when omitted.
        limit: max postings to return (bounded to ``_MAX_PAGES`` pages).
    """
    pages_needed = max(1, min(_MAX_PAGES, -(-limit // _RESULTS_PER_PAGE)))
    collected: list[dict] = []
    try:
        async with httpx.AsyncClient(
            timeout=20, headers=_HEADERS, follow_redirects=True
        ) as client:
            for page in range(1, pages_needed + 1):
                params = (
                    f"searchstring={quote_plus(query or '')}"
                    f"&locationstring={quote_plus(location or '')}"
                    f"&sort=M&page={page}"
                )
                resp = await client.get(f"{_SEARCH_URL}?{params}")
                if resp.status_code != 200:
                    break
                page_jobs = _parse_results(resp.text)
                if not page_jobs:
                    break
                collected.extend(page_jobs)
                if len(collected) >= limit:
                    break
    except Exception:
        logger.exception("Job Bank Canada search failed; failing soft to []")
        return []

    # De-dupe by external_id (pagination can overlap) and cap to limit.
    seen: set[str] = set()
    unique: list[dict] = []
    for job in collected:
        ext = job["external_id"]
        if ext in seen:
            continue
        seen.add(ext)
        unique.append(job)
    return unique[:limit]
