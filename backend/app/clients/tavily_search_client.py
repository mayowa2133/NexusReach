"""Tavily client for AI-native public-web discovery and corroboration."""

from __future__ import annotations

import re

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
    return ["theorg.com", "linkedin.com", "clay.earth", "contactout.com"]


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
    limit: int = 5,
) -> list[dict]:
    title_clause = brave_search_client._quoted_or_clause(titles, limit=2)
    title_part = f" {title_clause}" if title_clause else ""
    team_part = f' "{team_keywords[0]}"' if team_keywords else ""
    identity_part = ""
    if public_identity_terms:
        quoted_terms = [f'"{term}"' for term in public_identity_terms[:2] if term]
        if quoted_terms:
            identity_part = " " + " OR ".join(quoted_terms)
    query = f'"{company_name}"{title_part}{team_part}{identity_part}'

    results: list[dict] = []
    for item in await _run_tavily_query(
        query,
        max_results=limit,
        include_domains=_tavily_domains_for_public_people(),
    ):
        parsed = brave_search_client._parse_public_people_result(
            _normalize_tavily_result(item),
            company_name,
        )
        if not parsed:
            continue
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
