"""Google Custom Search API client for LinkedIn X-ray people discovery.

Uses Google Programmable Search Engine to find LinkedIn profiles of people
at target companies by job title. This is the free-tier fallback when
Apollo people search is unavailable.

Free quota: 100 queries/day (each query returns up to 10 results).
"""

import re

import httpx

from app.config import settings

GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


def _parse_linkedin_result(item: dict, company_name: str) -> dict | None:
    """Parse a Google CSE result item into a person data dict.

    Google returns LinkedIn results with titles like:
        "Jane Doe - Software Engineer - Google | LinkedIn"
        "John Smith - Senior Recruiter at Google | LinkedIn"

    Args:
        item: A single result item from Google CSE response.
        company_name: Company name for the result.

    Returns:
        Person dict matching _store_person() shape, or None if unparseable.
    """
    link = item.get("link", "")
    if not link or "/in/" not in link:
        return None

    # Clean the LinkedIn URL (remove query params)
    linkedin_url = re.split(r"[?#]", link)[0].rstrip("/")

    title_raw = item.get("title", "")
    # Remove " | LinkedIn" suffix
    title_clean = re.sub(r"\s*\|\s*LinkedIn\s*$", "", title_raw).strip()

    # Split on " - " to extract parts
    # Common formats: "Name - Title - Company", "Name - Title at Company"
    parts = [p.strip() for p in title_clean.split(" - ") if p.strip()]

    if not parts:
        return None

    full_name = parts[0]
    job_title = parts[1] if len(parts) > 1 else ""

    # Remove "at Company" from title if present
    job_title = re.sub(r"\s+at\s+.*$", "", job_title, flags=re.IGNORECASE).strip()

    # Skip if the "name" looks like a company page or generic result
    if not full_name or full_name.lower() == company_name.lower():
        return None

    return {
        "full_name": full_name,
        "title": job_title,
        "company": company_name,
        "department": "",
        "seniority": "",
        "linkedin_url": linkedin_url,
        "photo_url": "",
        "apollo_id": "",
        "source": "google_cse",
    }


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search for people at a company via Google CSE LinkedIn X-ray search.

    Builds a query like: site:linkedin.com/in "Google" "software engineer"
    and parses the results into person dicts.

    Args:
        company_name: Company name to search within.
        titles: Job title keywords to search for.
        team_keywords: Unused placeholder for interface compatibility.
        limit: Max results (capped at 10 per Google CSE limits).

    Returns:
        List of person dicts compatible with _store_person().
        Returns [] if API key or CSE ID is not configured.
    """
    if not settings.google_api_key or not settings.google_cse_id:
        return []

    # Build search query
    title_part = ""
    if titles:
        # Use first 2 titles to keep query focused
        quoted = [f'"{t}"' for t in titles[:2]]
        title_part = " " + " OR ".join(quoted)

    query = f'site:linkedin.com/in "{company_name}"{title_part}'

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                GOOGLE_CSE_URL,
                params={
                    "q": query,
                    "key": settings.google_api_key,
                    "cx": settings.google_cse_id,
                    "num": min(limit, 10),
                },
            )
            if resp.status_code in (403, 429):
                # Quota exceeded or forbidden
                return []
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return []

    items = data.get("items", [])
    results = []
    for item in items:
        person = _parse_linkedin_result(item, company_name)
        if person:
            results.append(person)

    return results[:limit]


async def search_exact_linkedin_profile(
    full_name: str,
    company_name: str,
    *,
    name_variants: list[str] | None = None,
    title_hints: list[str] | None = None,
    team_keywords: list[str] | None = None,
    limit: int = 3,
) -> list[dict]:
    """Search Google CSE for one exact LinkedIn profile."""
    if not settings.google_api_key or not settings.google_cse_id or not full_name or not company_name:
        return []

    ordered_names: list[str] = []
    seen_names: set[str] = set()
    for name in [full_name, *(name_variants or [])]:
        clean_name = (name or "").strip()
        if not clean_name or clean_name in seen_names:
            continue
        seen_names.add(clean_name)
        ordered_names.append(clean_name)

    queries: list[str] = [f'site:linkedin.com/in "{name}" "{company_name}"' for name in ordered_names]
    if title_hints:
        quoted = [f'"{t}"' for t in title_hints[:2] if t]
        if quoted:
            queries.extend(
                f'site:linkedin.com/in "{name}" "{company_name}" ' + " OR ".join(quoted)
                for name in ordered_names
            )
    if team_keywords:
        quoted_keywords = [f'"{keyword}"' for keyword in team_keywords[:2] if keyword]
        if quoted_keywords:
            queries.extend(
                f'site:linkedin.com/in "{name}" "{company_name}" ' + " OR ".join(quoted_keywords)
                for name in ordered_names
            )

    results = []
    seen_urls: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for query in queries:
                resp = await client.get(
                    GOOGLE_CSE_URL,
                    params={
                        "q": query,
                        "key": settings.google_api_key,
                        "cx": settings.google_cse_id,
                        "num": min(max(limit, 1), 10),
                    },
                )
                if resp.status_code in (403, 429):
                    return []
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("items", []):
                    person = _parse_linkedin_result(item, company_name)
                    if not person:
                        continue
                    linkedin_url = person.get("linkedin_url") or ""
                    if linkedin_url and linkedin_url in seen_urls:
                        continue
                    profile_data = dict(person.get("profile_data") or {})
                    profile_data["linkedin_backfill_query"] = query
                    profile_data["linkedin_backfill_result_url"] = linkedin_url
                    person["profile_data"] = profile_data
                    results.append(person)
                    if linkedin_url:
                        seen_urls.add(linkedin_url)
                if len(results) >= limit:
                    break
    except httpx.HTTPError:
        return []
    return results[:limit]
