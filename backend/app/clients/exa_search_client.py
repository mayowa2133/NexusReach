"""Exa search API client — datacenter-safe semantic people-discovery fallback.

Exa is a neural search API (authenticated REST, so it works from a cloud IP). It
is NOT a `site:`/boolean SERP product, so we use its `people` category with
`includeDomains=["linkedin.com"]` and natural-language queries as a *semantic*
people-discovery fallback for the bulk search_people family — not for exact
Boolean x-rays. No-op (returns ``[]``) when ``NEXUSREACH_EXA_API_KEY`` is unset.

NOTE: Exa retired the legacy `linkedin` category in favour of `people`; keep this
in sync with Exa's current API if their schema changes.
"""

import re

import httpx

from app.clients import brave_search_client
from app.config import settings
from app.utils.linkedin import parse_linkedin_serp_title

EXA_SEARCH_URL = "https://api.exa.ai/search"


def _parse_exa_result(item: dict, company_name: str) -> dict | None:
    link = item.get("url", "")
    if not link or "/in/" not in link:
        return None
    linkedin_url = re.split(r"[?#]", link)[0].rstrip("/")
    title_raw = item.get("title", "") or ""
    full_name, job_title, _ = parse_linkedin_serp_title(title_raw)
    if not full_name:
        # Exa profile titles are often just the person's name (no " - Title").
        full_name = re.split(r"\s+[-|]\s+", title_raw)[0].strip()
    if not full_name or full_name.lower() == company_name.lower():
        return None
    snippet = (item.get("text") or item.get("snippet") or "")[:500]
    location = brave_search_client._extract_candidate_location(title_raw, snippet)
    return {
        "full_name": full_name,
        "title": job_title,
        "company": company_name,
        "department": "",
        "seniority": "",
        "linkedin_url": linkedin_url,
        "photo_url": "",
        "apollo_id": "",
        "source": "exa",
        "snippet": snippet,
        "location": location,
        "profile_data": {
            "location": location,
            "location_source": "serp_snippet" if location else None,
        },
    }


async def _run_exa_people(query: str, num: int) -> list[dict]:
    if not settings.exa_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                EXA_SEARCH_URL,
                headers={"x-api-key": settings.exa_api_key, "content-type": "application/json"},
                json={
                    "query": query,
                    "category": "people",
                    "includeDomains": ["linkedin.com"],
                    "numResults": min(max(num, 1), 25),
                    "type": "auto",
                },
            )
            if resp.status_code in (401, 403, 429):
                return []
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    results = data.get("results")
    return results if isinstance(results, list) else []


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    geo_terms: list[str] | None = None,
    limit: int = 10,
    company_domain: str | None = None,
    debug_trace: dict[str, object] | None = None,
) -> list[dict]:
    """Semantic people search at a company via Exa's `people` category."""
    if not settings.exa_api_key:
        return []

    geo_clause = f" in {geo_terms[0]}" if geo_terms else ""
    queries: list[str] = []
    for title in (titles or [None])[:3]:
        if title:
            queries.append(f"{title} at {company_name}{geo_clause}")
        else:
            queries.append(f"people who work at {company_name}{geo_clause}")
    unique_queries = list(dict.fromkeys(queries))
    if debug_trace is not None:
        debug_trace["queries"] = unique_queries

    results: list[dict] = []
    seen_urls: set[str] = set()
    for query_index, query in enumerate(unique_queries):
        for item in await _run_exa_people(query, limit):
            person = _parse_exa_result(item, company_name)
            if not person:
                continue
            person = brave_search_client._attach_search_query_metadata(
                person, query=query, query_index=query_index, geo_terms=geo_terms
            )
            url = person.get("linkedin_url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            results.append(person)
        if len(results) >= limit:
            break
    return results[:limit]
