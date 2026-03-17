"""Brave Search API client for LinkedIn X-ray people discovery.

Uses Brave Web Search to find LinkedIn profiles of people at target
companies by job title.  This is the free-tier fallback when Apollo
people search is unavailable (Apollo returns 403 on free plan).

Pricing: $5/month free credits (~1 000 searches).  Each people search
uses 1 query and returns up to 20 results.
"""

import re

import httpx

from app.config import settings

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def _parse_linkedin_result(item: dict, company_name: str) -> dict | None:
    """Parse a Brave Search result into a person data dict.

    Brave returns LinkedIn results with titles like:
        "Jane Doe - Software Engineer - Google | LinkedIn"
        "John Smith - Senior Recruiter at Google | LinkedIn"

    Args:
        item: A single result from the Brave ``web.results`` array.
        company_name: Company name for the result.

    Returns:
        Person dict matching ``_store_person()`` shape, or ``None`` if
        unparseable or not a personal profile URL.
    """
    url = item.get("url", "")
    if not url or "/in/" not in url:
        return None

    # Clean the LinkedIn URL (remove query params)
    linkedin_url = re.split(r"[?#]", url)[0].rstrip("/")

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
        "source": "brave_search",
        "snippet": item.get("description", ""),
    }


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search for people at a company via Brave Web Search LinkedIn X-ray.

    Builds a query like: ``site:linkedin.com/in "Google" "software engineer"``
    and parses the results into person dicts.

    Args:
        company_name: Company name to search within.
        titles: Job title keywords to search for.
        team_keywords: Team-specific keywords from job context (e.g.
            ["payments", "infrastructure"]).  Only the first keyword is
            appended to avoid over-constraining the query.
        limit: Max results (capped at 20 per Brave API limits).

    Returns:
        List of person dicts compatible with ``_store_person()``.
        Returns ``[]`` if the Brave API key is not configured.
    """
    if not settings.brave_api_key:
        return []

    # Build search query
    title_part = ""
    if titles:
        # Use first 2 titles to keep query focused
        quoted = [f'"{t}"' for t in titles[:2]]
        title_part = " " + " OR ".join(quoted)

    team_part = ""
    if team_keywords:
        # Use only first keyword to avoid over-constraining
        team_part = f' "{team_keywords[0]}"'

    query = f'site:linkedin.com/in "{company_name}"{title_part}{team_part}'

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                BRAVE_SEARCH_URL,
                headers={"X-Subscription-Token": settings.brave_api_key},
                params={
                    "q": query,
                    "count": min(limit, 20),
                },
            )
            if resp.status_code in (401, 403, 429):
                # Auth error, forbidden, or rate-limited
                return []
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return []

    web = data.get("web", {})
    items = web.get("results", [])
    results = []
    for item in items:
        person = _parse_linkedin_result(item, company_name)
        if person:
            results.append(person)

    return results[:limit]


def _parse_hiring_team_result(item: dict, company_name: str) -> list[dict]:
    """Parse a LinkedIn job posting result for hiring team members.

    LinkedIn job pages sometimes include "Meet the hiring team" or show
    the recruiter/poster in the description snippet.  This function
    extracts person names and LinkedIn profile URLs when available.

    Args:
        item: A single Brave search result for a LinkedIn job page.
        company_name: Company name for context.

    Returns:
        List of person dicts (may be empty if no team info found).
    """
    description = item.get("description", "")
    url = item.get("url", "")
    results: list[dict] = []

    if not description and not url:
        return results

    # Look for LinkedIn profile URLs in the result's nested profile links
    # Brave sometimes includes profile_urls or deep_links
    # But primarily we parse the description for names

    # Pattern: "Posted by First Last" or "Hiring team: First Last, Title"
    # or "recruiter: First Last"
    patterns = [
        r"(?:posted by|hiring manager|recruiter)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)",
        r"(?:meet the (?:hiring )?team)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)",
    ]
    seen_names: set[str] = set()

    for pattern in patterns:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            name = match.group(1).strip()
            if name and name not in seen_names:
                seen_names.add(name)
                results.append({
                    "full_name": name,
                    "title": "",
                    "company": company_name,
                    "department": "",
                    "seniority": "",
                    "linkedin_url": "",
                    "photo_url": "",
                    "apollo_id": "",
                    "source": "brave_hiring_team",
                    "snippet": description[:200],
                })

    # Also look for LinkedIn /in/ profile URLs embedded in the description
    profile_urls = re.findall(
        r"https?://(?:www\.)?linkedin\.com/in/[\w-]+", description,
    )
    for profile_url in profile_urls:
        clean_url = re.split(r"[?#]", profile_url)[0].rstrip("/")
        if clean_url not in {r["linkedin_url"] for r in results}:
            # Extract name from URL slug as fallback
            slug = clean_url.rsplit("/in/", 1)[-1]
            name_guess = slug.replace("-", " ").title()
            results.append({
                "full_name": name_guess,
                "title": "",
                "company": company_name,
                "department": "",
                "seniority": "",
                "linkedin_url": clean_url,
                "photo_url": "",
                "apollo_id": "",
                "source": "brave_hiring_team",
                "snippet": description[:200],
            })

    return results


async def search_hiring_team(
    company_name: str,
    job_title: str,
    team_keywords: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search for the LinkedIn job posting to find hiring team members.

    Queries Brave for the job listing page which may include the
    recruiter, hiring manager, or "Meet the hiring team" section.

    Args:
        company_name: Company that posted the job.
        job_title: Title of the job posting.
        team_keywords: Optional team keywords to narrow the search.
        limit: Max results to return.

    Returns:
        List of person dicts with ``source="brave_hiring_team"``.
        Returns ``[]`` if no hiring team info is found.
    """
    if not settings.brave_api_key:
        return []

    team_part = ""
    if team_keywords:
        team_part = f' "{team_keywords[0]}"'

    query = f'site:linkedin.com/jobs "{company_name}" "{job_title}"{team_part}'

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                BRAVE_SEARCH_URL,
                headers={"X-Subscription-Token": settings.brave_api_key},
                params={
                    "q": query,
                    "count": 5,
                },
            )
            if resp.status_code in (401, 403, 429):
                return []
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return []

    web = data.get("web", {})
    items = web.get("results", [])
    results: list[dict] = []
    for item in items:
        results.extend(_parse_hiring_team_result(item, company_name))

    return results[:limit]
