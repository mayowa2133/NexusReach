"""Brave Search API client for LinkedIn X-ray people discovery.

Uses Brave Web Search to find LinkedIn profiles of people at target
companies by job title.  This is the free-tier fallback when Apollo
people search is unavailable (Apollo returns 403 on free plan).

Pricing: $5/month free credits (~1 000 searches).  Each people search
uses 1 query and returns up to 20 results.
"""

import re
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.utils.company_identity import extract_public_identity_hints

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
PUBLIC_RESULT_REJECTION_TERMS = (
    "email & phone",
    "phone number",
    "staff directory",
    "company profile",
    "contact info",
    "contact information",
    "directory",
)


def _clean_profile_url(url: str) -> str:
    return re.split(r"[?#]", url or "")[0].rstrip("/")


def _quoted_or_clause(terms: list[str] | None, *, limit: int) -> str:
    filtered = [f'"{term}"' for term in (terms or []) if term][:limit]
    if not filtered:
        return ""
    if len(filtered) == 1:
        return filtered[0]
    return f'({" OR ".join(filtered)})'


def _public_role_hint(titles: list[str] | None) -> str:
    normalized = " ".join(title.lower() for title in (titles or []) if title)
    if any(keyword in normalized for keyword in ("recruit", "talent acquisition", "sourcer", "campus", "university", "early careers", "early talent")):
        return '("recruiter" OR "recruiting" OR "talent acquisition" OR "sourcer")'
    if any(keyword in normalized for keyword in ("manager", "director", "lead")):
        return '("manager" OR "director" OR "lead")'
    return ""


async def _run_brave_query(query: str, count: int) -> list[dict]:
    if not settings.brave_api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                BRAVE_SEARCH_URL,
                headers={"X-Subscription-Token": settings.brave_api_key},
                params={"q": query, "count": min(count, 20)},
            )
            if resp.status_code in (401, 403, 429):
                return []
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return []

    return data.get("web", {}).get("results", [])


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
    linkedin_url = _clean_profile_url(url)

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
        "profile_data": {
            "linkedin_result_title": title_clean,
        },
    }


def _parse_public_people_result(item: dict, company_name: str) -> dict | None:
    """Parse a public-web result from org charts or recruiter posts."""
    title_raw = (item.get("title") or "").strip()
    description = item.get("description", "")
    url = (item.get("url") or "").strip()
    if not title_raw or not url:
        return None
    combined = f"{title_raw} {description}".lower()
    if any(term in combined for term in PUBLIC_RESULT_REJECTION_TERMS):
        return None

    clean_title = re.sub(r"\s*\|\s*[^|]+$", "", title_raw).strip()
    full_name = ""
    job_title = ""

    if " on LinkedIn:" in clean_title:
        full_name = clean_title.split(" on LinkedIn:", 1)[0].strip()
        title_match = re.search(
            rf"{re.escape(full_name)}\s+is\s+(?:a|an)\s+(.+?)\s+at\s+{re.escape(company_name)}",
            description,
            re.IGNORECASE,
        )
        if title_match:
            job_title = title_match.group(1).strip()
    else:
        match = re.match(
            rf"(?P<name>.+?)\s+-\s+(?P<title>.+?)(?:\s+at\s+{re.escape(company_name)}.*)?$",
            clean_title,
            re.IGNORECASE,
        )
        if match:
            full_name = match.group("name").strip()
            job_title = match.group("title").strip()

    if not full_name:
        return None
    if len(full_name.split()) < 2:
        return None
    if full_name.strip().lower() == company_name.strip().lower():
        return None
    if any(term in full_name.lower() for term in ("email", "phone", "directory", "profile")):
        return None

    parsed_url = urlparse(url)
    linkedin_url = _clean_profile_url(url) if "/in/" in parsed_url.path else ""
    source = "brave_public_web"
    public_url = _clean_profile_url(url)
    public_identity = extract_public_identity_hints(public_url)
    if public_identity.get("page_type") in {"team", "org"}:
        return None

    return {
        "full_name": full_name,
        "title": job_title,
        "company": company_name,
        "department": "",
        "seniority": "",
        "linkedin_url": linkedin_url,
        "apollo_id": "",
        "source": source,
        "snippet": description,
        "profile_data": {
            "public_url": public_url,
            "public_host": public_identity.get("host"),
            "public_identity_slug": public_identity.get("company_slug"),
            "public_page_type": public_identity.get("page_type"),
        },
    }


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    limit: int = 10,
    company_domain: str | None = None,
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
    # Build search query
    title_clause = _quoted_or_clause(titles, limit=2)
    title_part = f" {title_clause}" if title_clause else ""

    team_part = ""
    if team_keywords:
        # Use only first keyword to avoid over-constraining
        team_part = f' "{team_keywords[0]}"'

    domain_part = f' "{company_domain}"' if company_domain else ""

    queries: list[str] = []
    if company_domain:
        queries.append(f'site:linkedin.com/in "at {company_name}"{title_part}{team_part}')
        queries.append(f'"{company_name}" "{company_domain}" site:linkedin.com/in{title_part}')
    queries.append(f'site:linkedin.com/in "{company_name}"{domain_part}{title_part}{team_part}')

    results: list[dict] = []
    seen_urls: set[str] = set()
    for query in dict.fromkeys(queries):
        for item in await _run_brave_query(query, limit):
            person = _parse_linkedin_result(item, company_name)
            if not person:
                continue
            url = person.get("linkedin_url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            results.append(person)
        if len(results) >= limit:
            break
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
    """Search Brave for one person's LinkedIn profile at a target company."""
    if not full_name or not company_name:
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
    title_clause = _quoted_or_clause(title_hints, limit=2)
    if title_clause:
        queries.extend(
            f'site:linkedin.com/in "{name}" "{company_name}" {title_clause}'
            for name in ordered_names
        )

    keyword_clause = _quoted_or_clause(team_keywords, limit=2)
    if keyword_clause:
        queries.extend(
            f'site:linkedin.com/in "{name}" "{company_name}" {keyword_clause}'
            for name in ordered_names
        )

    results: list[dict] = []
    seen_urls: set[str] = set()
    for query in queries:
        items = await _run_brave_query(query, max(1, min(limit, 5)))
        for item in items:
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
    return results[:limit]


async def search_public_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    public_identity_terms: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search public web sources such as org charts and recruiter posts."""
    title_clause = _quoted_or_clause(titles, limit=2)
    title_part = f" {title_clause}" if title_clause else ""

    team_part = ""
    if team_keywords:
        team_part = f' "{team_keywords[0]}"'

    identity_part = ""
    if public_identity_terms:
        quoted_terms = [f'"{term}"' for term in public_identity_terms[:2] if term]
        if quoted_terms:
            identity_part = " " + " OR ".join(quoted_terms)

    queries: list[str] = []
    role_hint = _public_role_hint(titles)
    for slug in public_identity_terms[:2] if public_identity_terms else []:
        clean_slug = (slug or "").strip().lower()
        if not clean_slug:
            continue
        scoped_hint = role_hint or title_part.strip()
        if scoped_hint:
            queries.append(f'site:theorg.com/org/{clean_slug} "{company_name}" {scoped_hint}')
        else:
            queries.append(f'site:theorg.com/org/{clean_slug} "{company_name}"')

    queries.append(
        f'("{company_name}"{title_part}{team_part}{identity_part}) '
        '(site:theorg.com OR site:linkedin.com/posts OR site:clay.earth OR site:contactout.com)'
    )

    items: list[dict] = []
    seen_urls: set[str] = set()
    for query in dict.fromkeys(queries):
        for item in await _run_brave_query(query, limit):
            clean_url = _clean_profile_url(item.get("url", ""))
            key = clean_url or f'{item.get("title", "")}|{item.get("description", "")}'
            if key in seen_urls:
                continue
            seen_urls.add(key)
            items.append(item)

    results = []
    for item in items:
        person = _parse_public_people_result(item, company_name)
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
    team_part = ""
    if team_keywords:
        team_part = f' "{team_keywords[0]}"'

    query = f'site:linkedin.com/jobs "{company_name}" "{job_title}"{team_part}'
    items = await _run_brave_query(query, 5)
    results: list[dict] = []
    for item in items:
        results.extend(_parse_hiring_team_result(item, company_name))

    return results[:limit]


async def search_employment_sources(
    full_name: str,
    company_name: str,
    *,
    company_domain: str | None = None,
    public_identity_terms: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search public-web sources for current-employment corroboration."""
    if not full_name or not company_name:
        return []

    company_site = f" OR site:{company_domain}" if company_domain else ""
    identity_part = ""
    if public_identity_terms:
        quoted_terms = [f'"{term}"' for term in public_identity_terms[:2] if term]
        if quoted_terms:
            identity_part = " " + " OR ".join(quoted_terms)
    query = (
        f'"{full_name}" "{company_name}"{identity_part} '
        f'(site:theorg.com OR site:linkedin.com/posts OR site:medium.com OR '
        f'site:substack.com OR site:dev.to{company_site})'
    )
    items = await _run_brave_query(query, limit)
    results = []
    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "url": _clean_profile_url(url),
                "title": (item.get("title") or "").strip(),
                "description": (item.get("description") or "").strip(),
            }
        )
    return results[:limit]
