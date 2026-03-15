"""Proxycurl API client for LinkedIn profile enrichment."""

import httpx

from app.config import settings

PROXYCURL_BASE_URL = "https://nubela.co/proxycurl/api/v2"


async def enrich_profile(linkedin_url: str) -> dict | None:
    """Enrich a LinkedIn profile URL with full profile data.

    Args:
        linkedin_url: Full LinkedIn profile URL.

    Returns:
        Enriched profile dict or None if not found.
    """
    if not settings.proxycurl_api_key:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{PROXYCURL_BASE_URL}/linkedin",
            params={"linkedin_profile_url": linkedin_url, "use_cache": "if-present"},
            headers={"Authorization": f"Bearer {settings.proxycurl_api_key}"},
        )

        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

    experiences = data.get("experiences", []) or []
    education = data.get("education", []) or []

    return {
        "full_name": data.get("full_name", ""),
        "title": data.get("occupation", ""),
        "headline": data.get("headline", ""),
        "summary": data.get("summary", ""),
        "city": data.get("city", ""),
        "country": data.get("country_full_name", ""),
        "linkedin_url": linkedin_url,
        "photo_url": data.get("profile_pic_url", ""),
        "experiences": [
            {
                "company": exp.get("company", ""),
                "title": exp.get("title", ""),
                "starts_at": exp.get("starts_at"),
                "ends_at": exp.get("ends_at"),
                "description": exp.get("description", ""),
            }
            for exp in experiences[:5]
        ],
        "education": [
            {
                "school": edu.get("school", ""),
                "degree": edu.get("degree_name", ""),
                "field": edu.get("field_of_study", ""),
            }
            for edu in education[:3]
        ],
        "skills": data.get("skills", []) or [],
        "source": "proxycurl",
    }


async def search_people(
    company_name: str,
    role: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search for people by company using Proxycurl's people search.

    Note: This endpoint may require a higher-tier Proxycurl plan.
    Falls back gracefully if unavailable.
    """
    if not settings.proxycurl_api_key:
        return []

    params: dict = {
        "company_name": company_name,
        "page_size": min(limit, 10),
    }
    if role:
        params["current_role_title"] = role

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{PROXYCURL_BASE_URL}/search/person",
                params=params,
                headers={"Authorization": f"Bearer {settings.proxycurl_api_key}"},
            )
            if resp.status_code in (402, 403):
                # Plan doesn't support this endpoint
                return []
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "full_name": p.get("name", ""),
                "title": p.get("title", ""),
                "linkedin_url": p.get("linkedin_profile_url", ""),
                "source": "proxycurl",
            }
            for p in data.get("results", [])
        ]
    except httpx.HTTPError:
        return []
