"""Board-backed ATS search APIs (Greenhouse, Lever, Ashby, Workable)."""

from __future__ import annotations


import httpx
from app.clients.ats.html import _epoch_ms_to_iso, _humanize_company_slug


# The board crawls fan out over ~1k boards; passing one shared ``client``
# through the whole run reuses keep-alive connections to the three ATS API
# hosts instead of paying a TLS handshake per board. When ``client`` is None
# each call owns a short-lived client — identical to the old behavior, so
# interactive one-off searches and existing tests are unaffected.


async def search_greenhouse(
    company_slug: str,
    limit: int | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Fetch open jobs from a Greenhouse company board."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(url, params={"content": "true"}, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    jobs = [
        {
            "external_id": f"gh_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": data.get("name", company_slug),
            "location": (j.get("location", {}) or {}).get("name", ""),
            "remote": "remote" in (j.get("title", "") + (j.get("location", {}) or {}).get("name", "")).lower(),
            "url": j.get("absolute_url", ""),
            "apply_url": f"{j.get('absolute_url', '')}#app" if j.get("absolute_url") else None,
            "description": j.get("content", ""),
            "posted_at": j.get("updated_at") or None,
            "source": "greenhouse",
            "ats": "greenhouse",
            "ats_slug": company_slug,
        }
        for j in data.get("jobs", [])
    ]
    return jobs[:limit] if limit is not None else jobs


async def search_lever(
    company_slug: str,
    limit: int | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Fetch open jobs from a Lever company board."""
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(url, params={"mode": "json"}, timeout=15)
        if resp.status_code != 200:
            return []
        postings = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    if not isinstance(postings, list):
        return []

    normalized = [
        {
            "external_id": f"lv_{p.get('id', '')}",
            "title": p.get("text", ""),
            "company_name": _humanize_company_slug(company_slug),
            "location": p.get("categories", {}).get("location", ""),
            "remote": "remote" in (p.get("text", "") + p.get("categories", {}).get("location", "")).lower(),
            "url": p.get("hostedUrl", "") or p.get("applyUrl", ""),
            "apply_url": p.get("applyUrl", "") or p.get("hostedUrl", "") or None,
            "description": p.get("descriptionPlain", "") or p.get("description", ""),
            "department": p.get("categories", {}).get("department", ""),
            "posted_at": _epoch_ms_to_iso(p.get("createdAt")),
            "source": "lever",
            "ats": "lever",
            "ats_slug": company_slug,
        }
        for p in postings
    ]
    return normalized[:limit] if limit is not None else normalized


async def search_ashby(
    company_slug: str,
    limit: int | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Fetch open jobs from an Ashby job board."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    jobs = [
        {
            "external_id": f"ab_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": data.get("organizationName", company_slug),
            "location": j.get("location", ""),
            "remote": j.get("isRemote", False) or "remote" in j.get("location", "").lower(),
            "url": j.get("jobUrl", ""),
            "apply_url": f"{j.get('jobUrl', '')}/application" if j.get("jobUrl") else None,
            "description": j.get("descriptionHtml", "") or j.get("descriptionPlain", ""),
            "department": j.get("department", ""),
            "posted_at": j.get("publishedAt") or None,
            "source": "ashby",
            "ats": "ashby",
            "ats_slug": company_slug,
        }
        for j in data.get("jobs", [])
    ]
    return jobs[:limit] if limit is not None else jobs


def _workable_location(raw_job: dict) -> str:
    locations = raw_job.get("locations") or []
    primary = raw_job.get("location") or (locations[0] if locations else {}) or {}
    parts = [
        primary.get("city") or "",
        primary.get("region") or "",
        primary.get("country") or "",
    ]
    return ", ".join(part for part in parts if part)


async def search_workable(
    company_slug: str,
    *,
    job_shortcode: str,
) -> list[dict]:
    """Fetch a single public Workable job by shortcode from a direct job URL."""
    job_url = f"https://apply.workable.com/api/v2/accounts/{company_slug}/jobs/{job_shortcode}"
    account_url = f"https://apply.workable.com/api/v1/accounts/{company_slug}"

    async with httpx.AsyncClient(timeout=15) as client:
        job_resp = await client.get(job_url)
        if job_resp.status_code != 200:
            return []
        raw_job = job_resp.json()

        account_resp = await client.get(account_url, params={"full": "true"})
        account_name = company_slug
        if account_resp.status_code == 200:
            account_name = account_resp.json().get("name", company_slug)

    shortcode = raw_job.get("shortcode") or job_shortcode
    workplace = raw_job.get("workplace", "")
    remote = bool(raw_job.get("remote")) or workplace == "remote"
    work_mode = workplace if workplace in {"remote", "hybrid"} else ("remote" if remote else None)
    department = raw_job.get("department") or []
    if isinstance(department, list):
        department_value = ", ".join(item for item in department if item)
    else:
        department_value = str(department or "")

    posting_url = f"https://apply.workable.com/{company_slug}/j/{shortcode}"
    return [
        {
            "external_id": f"wk_{shortcode}",
            "title": raw_job.get("title", ""),
            "company_name": account_name,
            "location": _workable_location(raw_job),
            "remote": remote,
            "work_mode": work_mode,
            "url": posting_url,
            "apply_url": posting_url,
            "description": raw_job.get("description", ""),
            "department": department_value,
            "employment_type": raw_job.get("type"),
            "posted_at": raw_job.get("published") or None,
            "source": "workable",
            "ats": "workable",
            "ats_slug": company_slug,
        }
    ]
