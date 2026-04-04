"""Client for newgrad-jobs.com — scrapes server-rendered job listings."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

logger = logging.getLogger(__name__)

BASE_URL = "https://www.newgrad-jobs.com"
REQUEST_HEADERS = {"User-Agent": "NexusReach/1.0"}
DEFAULT_TIMEOUT = 20
DETAIL_CONCURRENCY = 8

# Categories that map to the site's URL structure (/list-{category})
CATEGORIES = [
    "software-engineer-jobs",
    "data-analyst",
    "cyber-security",
    "remote",
    "ux-designer",
]

_SALARY_RE = re.compile(r"\$(\d+(?:\.\d+)?)K(?:/yr)?(?:\s*-\s*\$(\d+(?:\.\d+)?)K(?:/yr)?)?", re.IGNORECASE)
_HIDDEN_CLASS_NAMES = {"w-condition-invisible"}
_EMPLOYMENT_TYPE_MAP = {
    "full-time": "full-time",
    "part-time": "part-time",
    "contract": "contract",
    "temporary": "temporary",
    "internship": "internship",
    "intern": "internship",
}
_WORK_MODE_RE = re.compile(r"^(remote|hybrid|on[- ]?site)$", re.IGNORECASE)
_LEVEL_HINT_RE = re.compile(
    r"\b(entry|new grad|graduate|intern|co-?op|associate|junior|mid|senior)\b",
    re.IGNORECASE,
)


def _try_parse_date(text: str) -> str:
    """Try to parse a date string, return ISO string or empty."""
    try:
        dt = datetime.strptime(text.strip(), "%B %d, %Y")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, AttributeError):
        return ""


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_salary(text: str) -> tuple[float | None, float | None, str]:
    """Extract salary range from text like '$115K/yr - $180K/yr'."""
    match = _SALARY_RE.search(text)
    if not match:
        return None, None, "USD"
    minimum = float(match.group(1)) * 1000 if match.group(1) else None
    maximum = float(match.group(2)) * 1000 if match.group(2) else None
    return minimum, maximum, "USD"


def build_external_id_from_url(job_url: str | None) -> str | None:
    """Build the stable external_id used for newgrad-jobs rows from a listing URL."""
    if not job_url:
        return None
    parsed = urlparse(job_url)
    path = parsed.path.rstrip("/")
    slug = path.rsplit("/", 1)[-1].strip()
    if not slug:
        return None
    return f"newgrad_{slug}"


def _is_hidden_tag(tag: Tag) -> bool:
    if getattr(tag, "attrs", None) is None:
        return False
    classes = tag.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    if any(class_name in _HIDDEN_CLASS_NAMES for class_name in classes):
        return True

    if tag.has_attr("hidden"):
        return True

    aria_hidden = str(tag.get("aria-hidden", "")).strip().lower()
    if aria_hidden == "true":
        return True

    style = str(tag.get("style", "")).replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _make_visible_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for selector in ("script", "style", "noscript"):
        for tag in soup.find_all(selector):
            tag.decompose()

    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(True)):
            if _is_hidden_tag(tag):
                tag.decompose()
                changed = True
    return soup


def _normalize_employment_type(text: str) -> str | None:
    normalized = _normalize_whitespace(text).lower()
    return _EMPLOYMENT_TYPE_MAP.get(normalized)


def _extract_meta_items(header: Tag | None) -> list[str]:
    if header is None:
        return []

    meta_root = header.find("div", class_="w-richtext")
    if meta_root is None:
        return []

    items = [
        _normalize_whitespace(item.get_text(" ", strip=True))
        for item in meta_root.select(".div-block-143")
    ]
    items = [item for item in items if item]
    if items:
        return items

    return [
        _normalize_whitespace(line)
        for line in meta_root.get_text("\n", strip=True).splitlines()
        if _normalize_whitespace(line)
    ]


def _build_description_html(header: Tag | None) -> str:
    if header is None:
        return ""

    parts: list[str] = []
    intro = header.select_one(".rich-text-block-20.w-richtext")
    if intro is not None:
        parts.append(str(intro))

    content = header.find_next_sibling("div", class_="detail-block-content-2")
    if content is not None:
        parts.append(str(content))

    return "\n".join(parts).strip()


def parse_job_list_html(
    html: str,
    *,
    category: str,
    limit: int = 100,
) -> list[dict]:
    """Parse a category listing page into normalized job rows."""
    soup = BeautifulSoup(html, "html.parser")

    # Each job has two <a> tags with the same href:
    #   1. A logo-only link (class="w-inline-block", no text)
    #   2. A text link (class="flex-block-27 w-inline-block") containing:
    #      - p.jobtitle: job title
    #      - p.jobtime: date like "March 31, 2026"
    #      - p.companyname_list: company name
    # We target the text links by looking for stripped_strings.
    link_prefix = f"/list-{category}/"
    job_links = [
        link
        for link in soup.find_all("a", href=True)
        if link["href"].startswith(link_prefix) and list(link.stripped_strings)
    ]

    jobs: list[dict] = []
    seen_slugs: set[str] = set()

    for link in job_links:
        href = link["href"]
        slug = href[len(link_prefix):]
        if slug in seen_slugs or not slug:
            continue
        seen_slugs.add(slug)

        title_el = link.select_one("p.jobtitle, .jobtitle")
        date_el = link.select_one("p.jobtime, .jobtime")
        company_el = link.select_one("p.companyname_list, .companyname_list")

        title = title_el.get_text(strip=True) if title_el else ""
        posted_at = _try_parse_date(date_el.get_text(strip=True)) if date_el else ""
        company = company_el.get_text(strip=True) if company_el else ""

        if not title:
            text_parts = [_normalize_whitespace(text) for text in link.stripped_strings]
            for part in text_parts:
                if not part:
                    continue
                parsed_date = _try_parse_date(part)
                if parsed_date:
                    posted_at = posted_at or parsed_date
                elif not title:
                    title = part
                elif not company:
                    company = part

        if not title:
            continue

        job_url = f"{BASE_URL}{href}"
        jobs.append({
            "external_id": build_external_id_from_url(job_url),
            "title": title,
            "company_name": company,
            "location": "",
            "remote": category == "remote",
            "url": job_url,
            "description": "",
            "posted_at": posted_at,
            "source": "newgrad_jobs",
        })

        if len(jobs) >= limit:
            break

    return jobs


def parse_job_detail_html(html: str) -> dict:
    """Parse a newgrad-jobs detail page into normalized metadata."""
    soup = _make_visible_soup(html)
    header = soup.select_one(".detail-block-header-2")

    meta_items = _extract_meta_items(header)
    description_html = _build_description_html(header)

    location = ""
    employment_type: str | None = None
    work_mode = ""
    level_label = ""
    salary_min, salary_max, salary_currency = None, None, "USD"

    for item in meta_items:
        if not item:
            continue
        salary_candidate = _parse_salary(item)
        if salary_candidate[0] is not None or salary_candidate[1] is not None:
            salary_min, salary_max, salary_currency = salary_candidate
            continue

        normalized_employment_type = _normalize_employment_type(item)
        if normalized_employment_type:
            employment_type = normalized_employment_type
            continue

        if _WORK_MODE_RE.match(item):
            work_mode = item
            continue

        if _LEVEL_HINT_RE.search(item):
            level_label = item
            continue

        if not location:
            location = item

    visible_header_text = _normalize_whitespace(header.get_text(" ", strip=True)) if header else ""
    is_closed = "this job has closed." in visible_header_text.lower()

    return {
        "location": location,
        "employment_type": employment_type,
        "work_mode": work_mode,
        "remote": work_mode.lower() == "remote" if work_mode else None,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "description": description_html,
        "level_label": level_label,
        "closed": is_closed,
    }


async def fetch_job_list(
    category: str = "software-engineer-jobs",
    limit: int = 100,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Fetch job listings from a newgrad-jobs.com category page."""
    url = f"{BASE_URL}/list-{category}"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True)

    try:
        resp = await client.get(url, headers=REQUEST_HEADERS)
        if resp.status_code != 200:
            logger.warning("newgrad-jobs returned %d for %s", resp.status_code, url)
            return []
        return parse_job_list_html(resp.text, category=category, limit=limit)
    finally:
        if owns_client:
            await client.aclose()


async def fetch_job_detail(
    job_url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict | None:
    """Fetch and parse an individual job detail page."""
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True)

    try:
        resp = await client.get(job_url, headers=REQUEST_HEADERS)
        if resp.status_code != 200:
            logger.warning("newgrad-jobs detail returned %d for %s", resp.status_code, job_url)
            return None
        return parse_job_detail_html(resp.text)
    finally:
        if owns_client:
            await client.aclose()


async def _enrich_job(job: dict, *, client: httpx.AsyncClient, semaphore: asyncio.Semaphore) -> dict | None:
    async with semaphore:
        detail = await fetch_job_detail(job["url"], client=client)
    if not detail:
        return job
    if detail.get("closed"):
        logger.info("Skipping closed newgrad job: %s", job["url"])
        return None
    merged = dict(job)
    if detail.get("remote") is None:
        detail = {key: value for key, value in detail.items() if key != "remote"}
    merged.update(detail)
    return merged


async def search_newgrad_jobs(
    query: str | None = None,
    category: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Search newgrad-jobs.com for jobs across multiple categories.

    If a specific category is given, only that category is scraped.
    Otherwise, all known categories are scraped for maximum coverage.
    If a query is provided, results are filtered client-side by title/company match.

    The site serves ~100 jobs per category. With 5 categories that gives up
    to ~500 unique jobs per scrape (some overlap between categories is deduped).
    """
    categories_to_search = [category] if category else CATEGORIES

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        all_jobs: list[dict] = []
        seen_ids: set[str] = set()

        for cat in categories_to_search:
            jobs = await fetch_job_list(category=cat, limit=100, client=client)
            for job in jobs:
                external_id = job.get("external_id")
                if external_id and external_id in seen_ids:
                    continue
                if external_id:
                    seen_ids.add(external_id)
                all_jobs.append(job)

        if query:
            keywords = query.lower().split()
            all_jobs = [
                job
                for job in all_jobs
                if any(
                    keyword in job["title"].lower() or keyword in job.get("company_name", "").lower()
                    for keyword in keywords
                )
            ]

        all_jobs = all_jobs[:limit]
        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
        enriched_jobs = await asyncio.gather(
            *[_enrich_job(job, client=client, semaphore=semaphore) for job in all_jobs]
        )

    return [job for job in enriched_jobs if job is not None][:limit]
