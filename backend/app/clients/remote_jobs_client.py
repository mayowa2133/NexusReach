"""Clients for remote/niche job boards — Dice, Remotive, Jobicy, SimplifyJobs."""

import asyncio
import base64
import hashlib
import html
import json
import logging
import re
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.config import settings


logger = logging.getLogger(__name__)

DICE_SEARCH_FIELDS = (
    "id|jobId|guid|summary|title|postedDate|modifiedDate|"
    "jobLocation.displayName|detailsPageUrl|redirectUrl|companyLogoUrl|salary|"
    "clientBrandId|companyPageUrl|companyName|isRemote|employerType"
)


def _dice_headers() -> dict[str, str]:
    """Dice search auth header, sourced from env config (audit C4).

    The key must never be hardcoded in source. When unset, Dice search fails
    soft to an empty result set rather than raising.
    """
    return {"x-api-key": settings.dice_api_key}
DICE_DETAIL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DICE_APPLY_DETAIL_CONCURRENCY = 5


def _is_http_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _json_unescape(value: str) -> str:
    try:
        value = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        pass
    return html.unescape(value)


def _extract_dice_configured_url(apply_redirect_url: str | None) -> str | None:
    """Decode Dice apply-redirect payloads into the underlying application URL."""
    if not apply_redirect_url:
        return None

    parsed = urlparse(apply_redirect_url)
    apply_data = parse_qs(parsed.query).get("applyData")
    if not apply_data:
        return None

    encoded_payload = apply_data[0]
    padded_payload = encoded_payload + ("=" * (-len(encoded_payload) % 4))
    try:
        payload = json.loads(base64.b64decode(padded_payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        # Malformed base64 / non-UTF-8 payloads must not crash enrichment (audit L15).
        return None

    configured_url = payload.get("configuredUrl")
    if isinstance(configured_url, str) and _is_http_url(configured_url):
        return configured_url
    return None


def _extract_dice_apply_url_from_html(page_html: str) -> str | None:
    """Extract the employer apply URL embedded in Dice's Next.js detail HTML."""
    pages = [page_html]
    normalized_html = page_html.replace(r"\"", '"')
    if normalized_html != page_html:
        pages.append(normalized_html)

    pattern = r'"applicationDetail":\{[^{}]*"url":"(?P<url>(?:\\.|[^"\\])*)"'
    for candidate_html in pages:
        match = re.search(pattern, candidate_html)
        if not match:
            continue
        url = _json_unescape(match.group("url"))
        if _is_http_url(url):
            return url
    return None


async def _fetch_dice_apply_url(
    client: httpx.AsyncClient,
    details_url: str | None,
) -> str | None:
    configured_url = _extract_dice_configured_url(details_url)
    if configured_url:
        return configured_url
    if not details_url or "/job-detail/" not in details_url:
        return None

    try:
        resp = await client.get(
            details_url,
            headers=DICE_DETAIL_HEADERS,
            follow_redirects=True,
            timeout=10,
        )
    except httpx.HTTPError as exc:
        logger.debug("Failed to fetch Dice detail page %s: %s", details_url, exc)
        return None

    if resp.status_code != 200:
        return None
    return _extract_dice_apply_url_from_html(resp.text)


async def _enrich_dice_apply_urls(
    jobs: list[dict],
    client: httpx.AsyncClient,
) -> None:
    semaphore = asyncio.Semaphore(DICE_APPLY_DETAIL_CONCURRENCY)

    async def enrich(job: dict) -> None:
        if job.get("apply_url"):
            return
        async with semaphore:
            apply_url = await _fetch_dice_apply_url(client, job.get("url"))
        if apply_url:
            job["apply_url"] = apply_url

    await asyncio.gather(*(enrich(job) for job in jobs))


async def resolve_dice_apply_urls(details_urls: list[str]) -> dict[str, str]:
    """Resolve Dice detail/redirect URLs to direct employer application URLs."""
    unique_urls = [url for url in dict.fromkeys(details_urls) if url]
    if not unique_urls:
        return {}

    results: dict[str, str] = {}
    semaphore = asyncio.Semaphore(DICE_APPLY_DETAIL_CONCURRENCY)

    async with httpx.AsyncClient(timeout=15) as client:
        async def resolve(details_url: str) -> None:
            async with semaphore:
                apply_url = await _fetch_dice_apply_url(client, details_url)
            if apply_url:
                results[details_url] = apply_url

        await asyncio.gather(*(resolve(url) for url in unique_urls))

    return results


async def _search_dice_with_client(
    client: httpx.AsyncClient,
    query: str,
    location: str | None = None,
    country_code: str | None = None,
    limit: int = 10,
) -> list[dict]:
    page_size = min(max(limit, 1), 20)
    max_pages = max(1, min((limit + page_size - 1) // page_size, 5))
    jobs: list[dict] = []
    for page in range(1, max_pages + 1):
        params: dict = {
            "q": query,
            "countryCode2": (country_code or "US").upper(),
            "radius": "30",
            "radiusUnit": "mi",
            "page": str(page),
            "pageSize": str(page_size),
            "fields": DICE_SEARCH_FIELDS,
        }
        if location:
            params["location"] = location

        resp = await client.get(
            "https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search",
            params=params,
            headers=_dice_headers(),
        )
        if resp.status_code != 200:
            break
        data = resp.json()
        page_jobs = data.get("data", [])
        if not page_jobs:
            break
        jobs.extend(page_jobs)
        if len(jobs) >= limit:
            break

    jobs = jobs[:limit]
    normalized_jobs = [
        {
            "external_id": f"dice_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": j.get("companyName", ""),
            "company_logo": j.get("companyLogoUrl"),
            "location": j.get("jobLocation", {}).get("displayName", ""),
            "remote": j.get("isRemote", False),
            "url": j.get("detailsPageUrl", ""),
            "apply_url": _extract_dice_configured_url(
                j.get("redirectUrl") or j.get("detailsPageUrl")
            ),
            "description": j.get("summary", ""),
            "posted_at": j.get("postedDate") or None,
            "source": "dice",
        }
        for j in jobs
    ]
    await _enrich_dice_apply_urls(normalized_jobs, client)
    return normalized_jobs


async def search_dice(
    query: str,
    location: str | None = None,
    country_code: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search Dice for tech jobs.

    Fails soft to ``[]`` when no API key is configured (audit C4) so a missing
    ``NEXUSREACH_DICE_API_KEY`` never breaks discovery for the other sources.
    """
    if not settings.dice_api_key:
        logger.info("Dice search skipped: NEXUSREACH_DICE_API_KEY is not configured.")
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        return await _search_dice_with_client(
            client, query, location=location, country_code=country_code, limit=limit
        )


async def search_remotive(query: str, limit: int = 10) -> list[dict]:
    """Search Remotive for remote jobs.

    Remotive's search is very literal — "Software Engineer" often returns 0.
    We try the full query first, then fall back to the first keyword.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://remotive.com/api/remote-jobs",
            params={"search": query, "limit": min(limit, 50)},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = data.get("jobs", [])

    # Fallback: try first keyword if full query returned nothing
    if not jobs and " " in query:
        first_keyword = query.split()[0]
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": first_keyword, "limit": min(limit, 50)},
            )
            if resp.status_code == 200:
                jobs = resp.json().get("jobs", [])

    jobs = jobs[:limit]
    return [
        {
            "external_id": f"remotive_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": j.get("company_name", ""),
            "location": j.get("candidate_required_location", "Worldwide"),
            "remote": True,
            "url": j.get("url", ""),
            "apply_url": j.get("url", "") or None,
            "description": j.get("description", ""),
            "employment_type": j.get("job_type", ""),
            "posted_at": j.get("publication_date") or None,
            "salary": j.get("salary", ""),
            "tags": j.get("tags", []),
            "source": "remotive",
        }
        for j in jobs
    ]


async def search_jobicy(query: str, limit: int = 10) -> list[dict]:
    """Search Jobicy for remote jobs."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": str(min(limit, 50)), "tag": query},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = data.get("jobs", [])[:limit]
    return [
        {
            "external_id": f"jobicy_{j.get('id', '')}",
            "title": j.get("jobTitle", ""),
            "company_name": j.get("companyName", ""),
            "location": j.get("jobGeo", "Remote"),
            "remote": True,
            "url": j.get("url", ""),
            "apply_url": j.get("url", "") or None,
            "description": j.get("jobDescription", ""),
            "employment_type": j.get("jobType", ""),
            "posted_at": j.get("pubDate") or None,
            "salary_min": j.get("annualSalaryMin"),
            "salary_max": j.get("annualSalaryMax"),
            "salary_currency": j.get("salaryCurrency", "USD"),
            "source": "jobicy",
        }
        for j in jobs
    ]


# SimplifyJobs prefixes "hot" companies with a 🔥 (and uses ⭐/✅ markers). Strip
# any leading emoji/symbol run so the company name matches real employers (needed
# for dedup + people discovery's company lookup). Excludes the arrow block so the
# "↳" repeat-company marker is left for the carry-forward logic to handle.
_SIMPLIFY_MARKER_RE = re.compile(
    r"^[\s☀-➿⬀-⯿\U0001F000-\U0001FAFF️‍]+"
)


def _strip_simplify_marker(company: str) -> str:
    return _SIMPLIFY_MARKER_RE.sub("", company or "").strip()


def _simplify_external_id(company: str, title: str, url: str) -> str:
    raw = f"{company.lower().strip()}|{title.lower().strip()}|{url.strip()}"
    return f"simplify_{hashlib.sha1(raw.encode()).hexdigest()[:16]}"


def _simplify_apply_url(cell: Tag) -> str:
    for link in cell.select("a[href]"):
        image_alt = " ".join(
            str(img.get("alt") or "")
            for img in link.select("img[alt]")
        ).lower()
        label = link.get_text(" ", strip=True).lower()
        href = str(link.get("href") or "").strip()
        if href and ("apply" in image_alt or "apply" in label):
            return href

    for link in cell.select("a[href]"):
        href = str(link.get("href") or "").strip()
        if href and "/p/" not in urlparse(href).path:
            return href
    return ""


def _parse_simplify_html_jobs(
    content: str, limit: int, *, level_label: str | None = None
) -> list[dict]:
    soup = BeautifulSoup(content, "html.parser")
    jobs: list[dict] = []
    last_company = ""
    for row in soup.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 4:
            continue

        row_text = row.get_text(" ", strip=True)
        if "🔒" in row_text or "closed" in row_text.lower():
            continue

        company = _strip_simplify_marker(cells[0].get_text(" ", strip=True))
        # SimplifyJobs repeats a company across roles with "↳"; carry it forward.
        if company in ("↳", "") or company.strip("* ") == "↳":
            company = last_company
        elif company:
            last_company = company
        title = cells[1].get_text(" ", strip=True)
        location = cells[2].get_text(", ", strip=True)
        url = _simplify_apply_url(cells[3])
        date_posted = cells[4].get_text(" ", strip=True) if len(cells) > 4 else ""

        if not company or not title or not url:
            continue

        jobs.append({
            "external_id": _simplify_external_id(company, title, url),
            "title": title,
            "company_name": company,
            "location": location,
            "remote": "remote" in location.lower(),
            "url": url,
            "apply_url": url,
            "description": f"{title} at {company} — {location}",
            "posted_at": date_posted or None,
            "level_label": level_label,
            "source": "simplify_github",
        })

        if len(jobs) >= limit:
            break

    return jobs


async def fetch_simplify_jobs(
    repo: str = "SimplifyJobs/New-Grad-Positions",
    limit: int = 50,
    *,
    level_label: str | None = None,
) -> list[dict]:
    """Parse job listings from SimplifyJobs GitHub markdown tables.

    Args:
        repo: GitHub repo path (SimplifyJobs/New-Grad-Positions or Summer2026-Internships).
        limit: Max results.
        level_label: Optional experience-level label stamped on every row. These
            repos are level-specific (a new-grad list, an internship list), so
            passing the level makes downstream classification exact instead of
            inferring it from the title.
    """
    # Fetch raw README
    url = f"https://raw.githubusercontent.com/{repo}/dev/README.md"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            # Try main branch
            url = f"https://raw.githubusercontent.com/{repo}/main/README.md"
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
        content = resp.text

    # Parse markdown table rows: | Company | Role | Location | Link | Date |
    # Pattern: lines starting with | that have multiple | separators
    rows = re.findall(r'^\|(.+)\|$', content, re.MULTILINE)
    if len(rows) < 2:
        return _parse_simplify_html_jobs(content, limit, level_label=level_label)

    # Skip header and separator rows
    jobs: list[dict] = []
    last_company = ""
    for row in rows[2:]:  # skip header + separator
        cols = [c.strip() for c in row.split("|")]
        if len(cols) < 4:
            continue

        company = _strip_simplify_marker(re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cols[0]))
        # SimplifyJobs repeats a company across multiple roles with a "↳" marker;
        # carry the previous company forward so those rows aren't dropped/mislabeled.
        if company in ("↳", "") or company.strip("* ") == "↳":
            company = last_company
        else:
            last_company = company
        title = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cols[1]).strip()
        location = cols[2].strip() if len(cols) > 2 else ""

        # Extract URL from markdown link
        link_match = re.search(r'\[([^\]]*)\]\(([^)]+)\)', cols[3] if len(cols) > 3 else "")
        url = link_match.group(2) if link_match else ""

        date_posted = cols[4].strip() if len(cols) > 4 else ""

        if not company or not title or company.startswith("---"):
            continue

        # Skip closed positions
        if "🔒" in row or "closed" in row.lower():
            continue

        jobs.append({
            "external_id": _simplify_external_id(company, title, url),
            "title": title,
            "company_name": company,
            "location": location,
            "remote": "remote" in location.lower(),
            "url": url,
            "apply_url": url or None,
            "description": f"{title} at {company} — {location}",
            "posted_at": date_posted or None,
            "level_label": level_label,
            "source": "simplify_github",
        })

        if len(jobs) >= limit:
            break

    return jobs


# Canonical, free, keyless GitHub lists of early-career tech roles. The new-grad
# repo was already used; the internships repo closes the biggest gap (internship
# volume was ~0). Each is level-specific, so we stamp the level on ingest.
_SIMPLIFY_EARLY_CAREER_REPOS: tuple[tuple[str, str], ...] = (
    ("SimplifyJobs/New-Grad-Positions", "New Grad"),
    ("SimplifyJobs/Summer2026-Internships", "Internship"),
    ("vanshb03/Summer2026-Internships", "Internship"),
)


async def fetch_simplify_early_career_jobs(limit_per_repo: int = 400) -> list[dict]:
    """Pull new-grad + internship roles from the curated SimplifyJobs lists.

    Aggregates every early-career repo (new-grad and internship), de-dupes by
    external id, and stamps each row's level from its source list. Free, keyless,
    fail-soft — a dead repo just contributes nothing.
    """
    batches = await asyncio.gather(
        *(
            fetch_simplify_jobs(repo, limit=limit_per_repo, level_label=label)
            for repo, label in _SIMPLIFY_EARLY_CAREER_REPOS
        ),
        return_exceptions=True,
    )
    seen: set[str] = set()
    out: list[dict] = []
    for batch in batches:
        if isinstance(batch, BaseException):
            logger.warning("Simplify early-career repo failed: %s", batch)
            continue
        for job in batch:
            key = job.get("external_id") or job.get("url") or job.get("title")
            if key in seen:
                continue
            seen.add(key)
            out.append(job)
    return out
