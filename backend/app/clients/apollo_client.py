"""Apollo.io API client for people and company search."""

import httpx

from app.config import settings

APOLLO_BASE_URL = "https://api.apollo.io/v1"


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    seniority: list[str] | None = None,
    departments: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search for people at a company by title and seniority.

    Args:
        company_name: Company name to search within.
        titles: Job title keywords (e.g. ["recruiter", "software engineer"]).
        seniority: Seniority levels (e.g. ["senior", "manager", "director"]).
        departments: Apollo department slugs (e.g. ["engineering_technical"]).
        limit: Max results to return.

    Returns:
        List of person dicts with name, title, company, linkedin_url, email, etc.
    """
    if not settings.apollo_api_key:
        return []

    params: dict = {
        "api_key": settings.apollo_api_key,
        "q_organization_name": company_name,
        "per_page": min(limit, 25),
    }

    if titles:
        params["person_titles"] = titles
    if seniority:
        params["person_seniorities"] = seniority
    if departments:
        params["person_departments"] = departments

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{APOLLO_BASE_URL}/mixed_people/search",
            json=params,
        )
        resp.raise_for_status()
        data = resp.json()

    people = data.get("people", [])
    return [
        {
            "full_name": p.get("name", ""),
            "title": p.get("title", ""),
            "company": p.get("organization", {}).get("name", company_name),
            "department": p.get("departments", [""])[0] if p.get("departments") else "",
            "seniority": p.get("seniority", ""),
            "linkedin_url": p.get("linkedin_url", ""),
            "work_email": p.get("email", ""),
            "email_verified": p.get("email_status") == "verified",
            "photo_url": p.get("photo_url", ""),
            "source": "apollo",
        }
        for p in people
    ]


async def search_company(company_name: str) -> dict | None:
    """Look up a company by name and return basic info."""
    if not settings.apollo_api_key:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{APOLLO_BASE_URL}/mixed_companies/search",
            json={
                "api_key": settings.apollo_api_key,
                "q_organization_name": company_name,
                "per_page": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    orgs = data.get("organizations", [])
    if not orgs:
        return None

    org = orgs[0]
    return {
        "name": org.get("name", company_name),
        "domain": org.get("primary_domain", ""),
        "size": org.get("estimated_num_employees", ""),
        "industry": org.get("industry", ""),
        "description": org.get("short_description", ""),
        "linkedin_url": org.get("linkedin_url", ""),
        "careers_url": org.get("website_url", ""),
    }
