"""Tavily client for AI-native public-web discovery and corroboration."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from app.clients import brave_search_client
from app.config import settings

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _normalize_tavily_result(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "description": item.get("content", ""),
    }


def _tavily_domains_for_public_people() -> list[str]:
    return ["theorg.com", "linkedin.com", "ca.linkedin.com", "clay.earth", "contactout.com"]


def _is_recruiter_public_search(titles: list[str] | None) -> bool:
    normalized = " ".join(title.lower() for title in (titles or []) if title)
    return any(keyword in normalized for keyword in ("recruit", "talent acquisition", "sourcer"))


def _is_peer_public_search(titles: list[str] | None) -> bool:
    if _is_recruiter_public_search(titles) or brave_search_client._is_manager_public_search(titles):
        return False
    return bool(titles)


def _is_manager_public_search(titles: list[str] | None) -> bool:
    if _is_recruiter_public_search(titles):
        return False
    return brave_search_client._is_manager_public_search(titles)


def _recruiter_targeted_queries(
    company_name: str,
    *,
    geo_terms: list[str] | None = None,
    team_keywords: list[str] | None = None,
) -> list[str]:
    geo_label = next((term for term in (geo_terms or []) if term and "," not in term), "")
    team_label = next((term for term in (team_keywords or []) if term), "")
    queries = [
        f'site:linkedin.com/in "{company_name}" recruiter {geo_label} Canada'.strip(),
        f'"{company_name}" recruiter {geo_label} Canada LinkedIn'.strip(),
        f'site:linkedin.com/in "{company_name}" "talent acquisition" {geo_label} Canada'.strip(),
        f'"{company_name}" "talent acquisition" {geo_label} Canada LinkedIn'.strip(),
        f'site:linkedin.com/in "{company_name}" ("lead talent acquisition" OR "head of talent acquisition" OR "talent acquisition leader") Canada'.strip(),
        f'"{company_name}" ("lead talent acquisition" OR "head of talent acquisition" OR "talent acquisition leader") Canada LinkedIn'.strip(),
        f'site:ca.linkedin.com/in "{company_name}" ("lead talent acquisition" OR "head of talent acquisition" OR recruiter) Toronto Canada'.strip(),
        f'site:linkedin.com/in "{company_name}" ("responsible for hiring in Canada" OR "hiring in Canada and the US" OR "hiring in Canada")'.strip(),
        f'"{company_name}" ("hiring in Canada" OR "responsible for hiring in Canada") LinkedIn'.strip(),
        f'"{company_name}" ("Canada recruiting lead" OR "Canada talent acquisition" OR "Canada recruiting") LinkedIn'.strip(),
        f'"{company_name}" "engineering recruiter" {geo_label} LinkedIn'.strip(),
        f'"{company_name}" "technical recruiter" {geo_label} LinkedIn'.strip(),
    ]
    if team_label:
        queries.append(f'"{company_name}" recruiter "{team_label}" {geo_label} LinkedIn'.strip())
    return [query for query in queries if query]


def _peer_targeted_queries(
    company_name: str,
    *,
    titles: list[str] | None = None,
    geo_terms: list[str] | None = None,
    team_keywords: list[str] | None = None,
) -> list[str]:
    geo_label = next((term for term in (geo_terms or []) if term and "," not in term), "")
    simplified_titles: list[str] = []
    for title in titles or []:
        clean = re.sub(r"\([^)]*\)", "", title or "").strip()
        clean = re.sub(r"\b(?:junior|associate|entry level|intern|i)\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" -")
        if not clean or clean.lower() in {value.lower() for value in simplified_titles}:
            continue
        simplified_titles.append(clean)
    role_labels = simplified_titles[:3] or ["Software Engineer", "Software Developer"]
    team_label = next((term for term in (team_keywords or []) if term), "")
    queries: list[str] = []
    for role_label in role_labels:
        queries.append(f'"{company_name}" "{role_label}" "{geo_label}" LinkedIn'.strip())
    if team_label:
        queries.append(f'"{company_name}" "{team_label}" "{geo_label}" LinkedIn'.strip())
    queries.extend(
        [
            f'"{company_name}" "software engineer" "{geo_label}" LinkedIn'.strip(),
            f'"{company_name}" "software developer" "{geo_label}" LinkedIn'.strip(),
        ]
    )
    return [query for query in queries if query]


async def _run_tavily_query(
    query: str,
    *,
    max_results: int,
    include_domains: list[str] | None = None,
) -> list[dict]:
    if not settings.tavily_api_key:
        return []

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "max_results": max(1, min(max_results, 10)),
        "search_depth": "basic",
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = include_domains

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(TAVILY_SEARCH_URL, json=payload)
            if resp.status_code in (401, 403, 429):
                return []
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return []

    return data.get("results", []) or []


async def search_public_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    public_identity_terms: list[str] | None = None,
    geo_terms: list[str] | None = None,
    limit: int = 5,
    debug_trace: dict[str, Any] | None = None,
) -> list[dict]:
    results: list[dict] = []
    queries: list[str] = []
    if _is_recruiter_public_search(titles):
        queries.extend(
            _recruiter_targeted_queries(
                company_name,
                geo_terms=geo_terms,
                team_keywords=team_keywords,
            )
        )
    elif _is_manager_public_search(titles):
        manager_queries = brave_search_client._manager_public_leader_queries(
            company_name,
            titles=titles,
            geo_terms=geo_terms,
            public_identity_terms=public_identity_terms,
        )
        queries.extend(manager_queries)
        geo_label = next((term for term in (geo_terms or []) if term and "," not in term), "")
        queries.extend(
            filter(
                None,
                [
                    f'"{company_name}" "Software Engineering Manager" "{geo_label}"',
                    f'"{company_name}" "Engineering Manager" "{geo_label}"',
                    f'"{company_name}" "Engineering Director" "{geo_label}"',
                    f'"{company_name} Canada" "Engineering Manager" "{geo_label}"',
                ],
            )
        )
    elif _is_peer_public_search(titles):
        queries.extend(
            _peer_targeted_queries(
                company_name,
                titles=titles,
                geo_terms=geo_terms,
                team_keywords=team_keywords,
            )
        )

    if not queries:
        title_clause = brave_search_client._quoted_or_clause(titles, limit=2)
        title_part = f" {title_clause}" if title_clause else ""
        team_part = f' "{team_keywords[0]}"' if team_keywords else ""
        geo_part = brave_search_client._geo_query_clause(geo_terms)
        identity_part = ""
        if public_identity_terms:
            quoted_terms = [f'"{term}"' for term in public_identity_terms[:2] if term]
            if quoted_terms:
                identity_part = " " + " OR ".join(quoted_terms)
        queries.append(f'"{company_name}"{title_part}{team_part}{identity_part}{geo_part}')

    unique_queries = list(dict.fromkeys(query for query in queries if query))
    if debug_trace is not None:
        debug_trace["queries"] = unique_queries

    seen_urls: set[str] = set()
    targeted_search = (
        _is_recruiter_public_search(titles)
        or _is_peer_public_search(titles)
        or _is_manager_public_search(titles)
    )
    per_query_limit = min(limit, 4 if targeted_search else limit)
    query_tasks = [
        _run_tavily_query(
            query,
            max_results=per_query_limit,
            include_domains=_tavily_domains_for_public_people(),
        )
        for query in unique_queries
    ]
    query_results = await asyncio.gather(*query_tasks)
    for query_index, item_batch in enumerate(query_results):
        query = unique_queries[query_index]
        for item in item_batch:
            parsed = brave_search_client._parse_public_people_result(
                _normalize_tavily_result(item),
                company_name,
            )
            if not parsed:
                continue
            url = parsed.get("linkedin_url") or parsed.get("profile_data", {}).get("public_url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            parsed = brave_search_client._attach_search_query_metadata(
                parsed,
                query=query,
                query_index=query_index,
                geo_terms=geo_terms,
            )
            parsed["source"] = "tavily_public_web"
            results.append(parsed)
    return results[:limit]


async def search_employment_sources(
    full_name: str,
    company_name: str,
    *,
    company_domain: str | None = None,
    public_identity_terms: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    if not full_name or not company_name:
        return []

    identity_part = ""
    if public_identity_terms:
        quoted_terms = [f'"{term}"' for term in public_identity_terms[:2] if term]
        if quoted_terms:
            identity_part = " " + " OR ".join(quoted_terms)
    query = f'"{full_name}" "{company_name}"{identity_part}'
    include_domains = ["theorg.com", "linkedin.com", "medium.com", "substack.com", "dev.to"]
    if company_domain:
        include_domains.append(company_domain)

    results: list[dict] = []
    for item in await _run_tavily_query(
        query,
        max_results=limit,
        include_domains=include_domains,
    ):
        url = (item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "url": re.split(r"[?#]", url)[0].rstrip("/"),
                "title": (item.get("title") or "").strip(),
                "description": (item.get("content") or "").strip(),
                "source": "tavily_public_web",
            }
        )
    return results[:limit]
