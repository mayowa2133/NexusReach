"""ATS (Applicant Tracking System) clients — Greenhouse, Lever, Ashby public APIs."""

import httpx


async def search_greenhouse(company_slug: str, limit: int = 20) -> list[dict]:
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

    jobs = data.get("jobs", [])[:limit]
    return [
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
        for j in jobs
    ]


async def search_lever(company_slug: str, limit: int = 20) -> list[dict]:
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

    return [
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
        for p in postings[:limit]
    ]


async def search_ashby(company_slug: str, limit: int = 20) -> list[dict]:
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

    jobs = data.get("jobs", [])[:limit]
    return [
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
        for j in jobs
    ]
