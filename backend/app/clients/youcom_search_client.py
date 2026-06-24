"""You.com Search API client — datacenter-safe SERP fallback for people discovery.

You.com's Search API supports `site:` / boolean operators and returns web results
as JSON from a server-side authenticated endpoint, so (unlike scraping) it works
from a cloud/datacenter IP. It slots in as an additional LinkedIn x-ray provider.

No-op (returns ``[]``) when ``NEXUSREACH_YOUCOM_API_KEY`` is unset, so it is safe
to leave registered before a key is configured. Reuses the same query-building
and SERP-title parsing as the Google/Brave clients so result shapes match.

NOTE: confirm the endpoint/response shape against your You.com plan when you add a
key — `_extract_hits` tolerates the common field names, and the client fails soft.
"""

import re

import httpx

from app.clients import brave_search_client
from app.config import settings
from app.utils.linkedin import parse_linkedin_serp_title

YOUCOM_SEARCH_URL = "https://api.ydc-index.io/search"


def _extract_hits(data: dict) -> list[dict]:
    for key in ("hits", "results", "web_results"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _hit_url(hit: dict) -> str:
    return hit.get("url") or hit.get("link") or ""


def _hit_snippet(hit: dict) -> str:
    snippets = hit.get("snippets")
    if isinstance(snippets, list) and snippets:
        return " ".join(s for s in snippets if isinstance(s, str))[:500]
    return (hit.get("description") or hit.get("snippet") or "")[:500]


def _parse_linkedin_hit(hit: dict, company_name: str) -> dict | None:
    link = _hit_url(hit)
    if not link or "/in/" not in link:
        return None
    linkedin_url = re.split(r"[?#]", link)[0].rstrip("/")
    title_raw = hit.get("title", "")
    full_name, job_title, _ = parse_linkedin_serp_title(title_raw)
    if not full_name or full_name.lower() == company_name.lower():
        return None
    snippet = _hit_snippet(hit)
    title_clean = re.sub(r"\s*\|\s*LinkedIn\s*$", "", title_raw).strip()
    location = brave_search_client._extract_candidate_location(title_clean, snippet)
    return {
        "full_name": full_name,
        "title": job_title,
        "company": company_name,
        "department": "",
        "seniority": "",
        "linkedin_url": linkedin_url,
        "photo_url": "",
        "apollo_id": "",
        "source": "youcom",
        "snippet": snippet,
        "location": location,
        "profile_data": {
            "location": location,
            "location_source": "serp_snippet" if location else None,
        },
    }


async def _run_youcom_query(query: str, num: int) -> list[dict]:
    if not settings.youcom_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                YOUCOM_SEARCH_URL,
                params={"query": query, "num_web_results": min(max(num, 1), 20)},
                headers={"X-API-Key": settings.youcom_api_key},
            )
            if resp.status_code in (401, 403, 429):
                return []
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    return _extract_hits(data)


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    geo_terms: list[str] | None = None,
    limit: int = 10,
    company_domain: str | None = None,
    debug_trace: dict[str, object] | None = None,
) -> list[dict]:
    """LinkedIn x-ray people search via You.com (`site:linkedin.com/in` queries)."""
    if not settings.youcom_api_key:
        return []

    from app.clients.serper_search_client import _title_batches

    geo_part = brave_search_client._geo_query_clause(geo_terms)
    domain_part = f' "{company_domain}"' if company_domain else ""

    queries: list[str] = []
    for query in brave_search_client._broad_role_queries(company_name, titles):
        if geo_part:
            queries.append(f"{query}{geo_part}")
        queries.append(query)
    for batch in _title_batches(titles, batch_size=2):
        quoted = [f'"{t}"' for t in batch if t]
        title_part = (" " + " OR ".join(quoted)) if quoted else ""
        if geo_part:
            queries.append(f'site:linkedin.com/in "{company_name}"{domain_part}{title_part}{geo_part}')
        queries.append(f'site:linkedin.com/in "{company_name}"{domain_part}{title_part}')

    unique_queries = list(dict.fromkeys(queries))
    if debug_trace is not None:
        debug_trace["queries"] = unique_queries

    results: list[dict] = []
    seen_urls: set[str] = set()
    for query_index, query in enumerate(unique_queries):
        for hit in await _run_youcom_query(query, limit):
            person = _parse_linkedin_hit(hit, company_name)
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


async def search_exact_linkedin_profile(
    full_name: str,
    company_name: str,
    *,
    name_variants: list[str] | None = None,
    title_hints: list[str] | None = None,
    team_keywords: list[str] | None = None,
    geo_terms: list[str] | None = None,
    limit: int = 3,
) -> list[dict]:
    """Find one exact LinkedIn profile via You.com."""
    if not settings.youcom_api_key or not full_name or not company_name:
        return []

    geo_part = brave_search_client._geo_query_clause(geo_terms)
    ordered_names: list[str] = []
    seen_names: set[str] = set()
    for name in [full_name, *(name_variants or [])]:
        clean = (name or "").strip()
        if clean and clean.lower() not in seen_names:
            seen_names.add(clean.lower())
            ordered_names.append(clean)

    queries = [f'site:linkedin.com/in "{name}" "{company_name}"{geo_part}' for name in ordered_names]
    if title_hints:
        quoted = [f'"{t}"' for t in title_hints[:2] if t]
        if quoted:
            queries.extend(
                f'site:linkedin.com/in "{name}" "{company_name}" ' + " OR ".join(quoted) + geo_part
                for name in ordered_names
            )

    results: list[dict] = []
    seen_urls: set[str] = set()
    for query in queries:
        for hit in await _run_youcom_query(query, limit):
            person = _parse_linkedin_hit(hit, company_name)
            if not person:
                continue
            url = person.get("linkedin_url") or ""
            if url and url in seen_urls:
                continue
            profile_data = dict(person.get("profile_data") or {})
            profile_data["linkedin_backfill_query"] = query
            profile_data["linkedin_backfill_result_url"] = url
            person["profile_data"] = profile_data
            results.append(person)
            if url:
                seen_urls.add(url)
        if len(results) >= limit:
            break
    return results[:limit]
