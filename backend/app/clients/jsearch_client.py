"""JSearch (RapidAPI) client for job search."""

import httpx

from app.config import settings

JSEARCH_BASE_URL = "https://jsearch.p.rapidapi.com"


def _headers() -> dict[str, str]:
    return {
        "X-RapidAPI-Key": settings.jsearch_api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }


async def search_jobs(
    query: str,
    location: str | None = None,
    remote_only: bool = False,
    date_posted: str = "week",
    limit: int = 10,
) -> list[dict]:
    """Search for jobs via JSearch.

    Args:
        query: Job title or keyword (e.g. "software engineer").
        location: Location filter (e.g. "New York, NY").
        remote_only: Only return remote jobs.
        date_posted: "all", "today", "3days", "week", "month".
        limit: Max results.

    Returns:
        Normalized list of job dicts.
    """
    if not settings.jsearch_api_key:
        return []

    q = query
    if location:
        q = f"{query} in {location}"

    params: dict = {
        "query": q,
        "num_pages": "1",
        "date_posted": date_posted,
    }
    if remote_only:
        params["remote_jobs_only"] = "true"

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{JSEARCH_BASE_URL}/search",
            params=params,
            headers=_headers(),
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = data.get("data", [])[:limit]
    return [
        {
            "external_id": j.get("job_id", ""),
            "title": j.get("job_title", ""),
            "company_name": j.get("employer_name", ""),
            "company_logo": j.get("employer_logo", ""),
            "location": j.get("job_city", "") or j.get("job_state", "") or j.get("job_country", ""),
            "remote": j.get("job_is_remote", False),
            "url": j.get("job_apply_link", "") or j.get("job_google_link", ""),
            "description": j.get("job_description", ""),
            "employment_type": j.get("job_employment_type", ""),
            "posted_at": j.get("job_posted_at_datetime_utc") or None,
            "salary_min": j.get("job_min_salary"),
            "salary_max": j.get("job_max_salary"),
            "salary_currency": j.get("job_salary_currency", "USD"),
            "source": "jsearch",
        }
        for j in jobs
    ]
