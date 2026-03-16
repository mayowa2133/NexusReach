"""Apollo.io API client for people discovery (free) and enrichment (credits)."""

import httpx

from app.config import settings

# Credit-consuming endpoints (enrichment, company search)
APOLLO_BASE_URL = "https://api.apollo.io/v1"

# Free discovery endpoint (no credits, no emails)
APOLLO_API_SEARCH_URL = "https://api.apollo.io/api/v1"


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    seniority: list[str] | None = None,
    departments: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search for people at a company using the free api_search endpoint.

    Uses /api/v1/mixed_people/api_search which does NOT consume credits
    but also does NOT return email addresses. Use enrich_person() separately
    to get emails (1 credit per call).

    Args:
        company_name: Company name to search within.
        titles: Job title keywords (e.g. ["recruiter", "software engineer"]).
        seniority: Seniority levels (e.g. ["senior", "manager", "director"]).
        departments: Apollo department slugs (e.g. ["engineering_technical"]).
        limit: Max results to return.

    Returns:
        List of person dicts with name, title, company, linkedin_url, apollo_id, etc.
        Does NOT include work_email — use enrich_person() for that.
    """
    api_key = settings.apollo_master_api_key or settings.apollo_api_key
    if not api_key:
        return []

    params: dict = {
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
            f"{APOLLO_API_SEARCH_URL}/mixed_people/api_search",
            headers={"X-Api-Key": api_key},
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
            "department": (
                p.get("departments", [""])[0] if p.get("departments") else ""
            ),
            "seniority": p.get("seniority", ""),
            "linkedin_url": p.get("linkedin_url", ""),
            "photo_url": p.get("photo_url", ""),
            "apollo_id": p.get("id", ""),
            "source": "apollo",
        }
        for p in people
    ]


async def enrich_person(
    apollo_id: str | None = None,
    linkedin_url: str | None = None,
    full_name: str | None = None,
    domain: str | None = None,
) -> dict | None:
    """Enrich a person to get their email address (costs 1 Apollo credit).

    Uses /v1/people/match which accepts various identifiers.
    Preferred lookup order: apollo_id > linkedin_url > name+domain.

    Args:
        apollo_id: Apollo person ID (most reliable).
        linkedin_url: LinkedIn profile URL.
        full_name: Person's full name (used with domain).
        domain: Company domain (used with full_name).

    Returns:
        Dict with work_email, email_verified, apollo_id, or None if no match.
    """
    if not settings.apollo_api_key:
        return None

    params: dict = {"api_key": settings.apollo_api_key}

    if apollo_id:
        params["id"] = apollo_id
    elif linkedin_url:
        params["linkedin_url"] = linkedin_url
    elif full_name and domain:
        parts = full_name.strip().split()
        if len(parts) >= 2:
            params["first_name"] = parts[0]
            params["last_name"] = " ".join(parts[1:])
            params["domain"] = domain
        else:
            return None
    else:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{APOLLO_BASE_URL}/people/match",
            json=params,
        )
        resp.raise_for_status()
        data = resp.json()

    person = data.get("person")
    if not person:
        return None

    email = person.get("email", "")
    if not email:
        return None

    return {
        "work_email": email,
        "email_verified": person.get("email_status") == "verified",
        "apollo_id": person.get("id", ""),
    }


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
