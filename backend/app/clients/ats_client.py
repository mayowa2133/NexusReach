"""ATS (Applicant Tracking System) clients — Greenhouse, Lever, Ashby public APIs."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx


@dataclass(frozen=True)
class ParsedATSJobURL:
    """Normalized ATS job URL metadata."""

    ats_type: str
    company_slug: str
    external_id: str | None = None
    canonical_url: str | None = None


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return parsed._replace(path=path, query="", fragment="").geturl()


def parse_ats_job_url(job_url: str) -> ParsedATSJobURL | None:
    """Parse a public ATS job URL into a board slug and exact job identity."""
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if not host:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)

    if "greenhouse.io" in host:
        if path_parts[:2] == ["embed", "job_app"]:
            company_slug = (query.get("for") or [None])[0]
            raw_job_id = (query.get("token") or query.get("job_id") or query.get("gh_jid") or [None])[0]
            if not company_slug:
                return None
            canonical_url = None
            external_id = None
            if raw_job_id:
                external_id = f"gh_{raw_job_id}"
                canonical_url = f"https://job-boards.greenhouse.io/{company_slug}/jobs/{raw_job_id}"
            return ParsedATSJobURL(
                ats_type="greenhouse",
                company_slug=company_slug,
                external_id=external_id,
                canonical_url=canonical_url,
            )

        if "jobs" in path_parts:
            jobs_index = path_parts.index("jobs")
            if jobs_index >= 1:
                company_slug = path_parts[jobs_index - 1]
                raw_job_id = path_parts[jobs_index + 1] if len(path_parts) > jobs_index + 1 else None
                canonical_url = _clean_url(job_url)
                external_id = f"gh_{raw_job_id}" if raw_job_id else None
                return ParsedATSJobURL(
                    ats_type="greenhouse",
                    company_slug=company_slug,
                    external_id=external_id,
                    canonical_url=canonical_url,
                )

    if "lever.co" in host:
        if len(path_parts) >= 1:
            company_slug = path_parts[0]
            raw_job_id = path_parts[1] if len(path_parts) > 1 else None
            external_id = f"lv_{raw_job_id}" if raw_job_id else None
            return ParsedATSJobURL(
                ats_type="lever",
                company_slug=company_slug,
                external_id=external_id,
                canonical_url=_clean_url(job_url),
            )

    if "ashbyhq.com" in host and host.startswith("jobs."):
        if len(path_parts) >= 1:
            company_slug = path_parts[0]
            raw_job_id = path_parts[1] if len(path_parts) > 1 else None
            external_id = f"ab_{raw_job_id}" if raw_job_id else None
            return ParsedATSJobURL(
                ats_type="ashby",
                company_slug=company_slug,
                external_id=external_id,
                canonical_url=_clean_url(job_url),
            )

    return None


async def search_greenhouse(company_slug: str, limit: int | None = None) -> list[dict]:
    """Fetch open jobs from a Greenhouse company board.

    Args:
        company_slug: Greenhouse board token (e.g. "stripe", "vercel").
        limit: Max results.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params={"content": "true"})
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = [
        {
            "external_id": f"gh_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": data.get("name", company_slug),
            "location": (j.get("location", {}) or {}).get("name", ""),
            "remote": "remote" in (j.get("title", "") + (j.get("location", {}) or {}).get("name", "")).lower(),
            "url": j.get("absolute_url", ""),
            "description": j.get("content", ""),
            "posted_at": j.get("updated_at", ""),
            "source": "greenhouse",
            "ats": "greenhouse",
            "ats_slug": company_slug,
        }
        for j in data.get("jobs", [])
    ]
    return jobs[:limit] if limit is not None else jobs


async def search_lever(company_slug: str, limit: int | None = None) -> list[dict]:
    """Fetch open jobs from a Lever company board.

    Args:
        company_slug: Lever company identifier (e.g. "stripe", "netflix").
        limit: Max results.
    """
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params={"mode": "json"})
        if resp.status_code != 200:
            return []
        postings = resp.json()

    if not isinstance(postings, list):
        return []

    postings_normalized = [
        {
            "external_id": f"lv_{p.get('id', '')}",
            "title": p.get("text", ""),
            "company_name": company_slug,
            "location": p.get("categories", {}).get("location", ""),
            "remote": "remote" in (p.get("text", "") + p.get("categories", {}).get("location", "")).lower(),
            "url": p.get("hostedUrl", "") or p.get("applyUrl", ""),
            "description": p.get("descriptionPlain", "") or p.get("description", ""),
            "department": p.get("categories", {}).get("department", ""),
            "posted_at": "",
            "source": "lever",
            "ats": "lever",
            "ats_slug": company_slug,
        }
        for p in postings
    ]
    return postings_normalized[:limit] if limit is not None else postings_normalized


async def search_ashby(company_slug: str, limit: int | None = None) -> list[dict]:
    """Fetch open jobs from an Ashby job board.

    Args:
        company_slug: Ashby board identifier.
        limit: Max results.
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = [
        {
            "external_id": f"ab_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": data.get("organizationName", company_slug),
            "location": j.get("location", ""),
            "remote": j.get("isRemote", False) or "remote" in j.get("location", "").lower(),
            "url": j.get("jobUrl", ""),
            "description": j.get("descriptionHtml", "") or j.get("descriptionPlain", ""),
            "department": j.get("department", ""),
            "posted_at": j.get("publishedAt", ""),
            "source": "ashby",
            "ats": "ashby",
            "ats_slug": company_slug,
        }
        for j in data.get("jobs", [])
    ]
    return jobs[:limit] if limit is not None else jobs
