"""Adzuna API client for job search."""

import httpx

from app.config import settings

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"


async def search_jobs(
    query: str,
    location: str | None = None,
    country: str = "us",
    limit: int = 10,
) -> list[dict]:
    """Search for jobs via Adzuna.

    Args:
        query: Job title or keyword.
        location: Location filter.
        country: Country code (e.g. "us", "gb", "ca").
        limit: Max results.

    Returns:
        Normalized list of job dicts.
    """
    if not settings.adzuna_app_id or not settings.adzuna_api_key:
        return []

    params: dict = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_api_key,
        "results_per_page": min(limit, 50),
        "what": query,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{ADZUNA_BASE_URL}/{country}/search/1",
            params=params,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = data.get("results", [])[:limit]
    return [
        {
            "external_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "company_name": j.get("company", {}).get("display_name", ""),
            "location": j.get("location", {}).get("display_name", ""),
            "remote": "remote" in j.get("title", "").lower() or "remote" in j.get("description", "").lower(),
            "url": j.get("redirect_url", ""),
            "description": j.get("description", ""),
            "employment_type": j.get("contract_time", ""),
            "posted_at": j.get("created") or None,
            "salary_min": j.get("salary_min"),
            "salary_max": j.get("salary_max"),
            "salary_currency": "USD" if country == "us" else "GBP" if country == "gb" else "USD",
            "source": "adzuna",
        }
        for j in jobs
    ]
