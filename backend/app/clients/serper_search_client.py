"""Serper SERP client for LinkedIn x-ray and public-web discovery."""

from __future__ import annotations

import re

import httpx

from app.clients import brave_search_client
from app.config import settings

SERPER_SEARCH_URL = "https://google.serper.dev/search"


def _serper_item_to_brave_item(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "url": item.get("link", ""),
        "description": item.get("snippet", ""),
    }


def _relabel_result(result: dict, *, source: str) -> dict:
    updated = dict(result)
    updated["source"] = source
    return updated


async def _run_serper_query(query: str, num: int) -> list[dict]:
    if not settings.serper_api_key:
        return []

    payload = {
        "q": query,
        "num": min(max(num, 1), 10),
    }
    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                SERPER_SEARCH_URL,
                headers=headers,
                json=payload,
            )
            if resp.status_code in (401, 403, 429):
                return []
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError:
        return []

    return data.get("organic", []) or []


def _title_batches(
    titles: list[str] | None,
    batch_size: int = 2,
    max_batches: int = 3,
) -> list[list[str]]:
    """Split titles into groups of *batch_size* for query expansion.

    Returns at most *max_batches* groups to keep API calls reasonable.
    """
    if not titles:
        return [[]]
    batches: list[list[str]] = []
    for i in range(0, len(titles), batch_size):
        batches.append(titles[i : i + batch_size])
        if len(batches) >= max_batches:
            break
    return batches or [[]]


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    limit: int = 10,
    company_domain: str | None = None,
) -> list[dict]:
    team_part = f' "{team_keywords[0]}"' if team_keywords else ""
    domain_part = f' "{company_domain}"' if company_domain else ""

    # Build queries for each batch of titles so we cover the full list
    queries: list[str] = []
    for batch in _title_batches(titles, batch_size=2):
        title_clause = brave_search_client._quoted_or_clause(batch, limit=2)
        title_part = f" {title_clause}" if title_clause else ""
        if company_domain:
            queries.append(f'site:linkedin.com/in "at {company_name}"{title_part}{team_part}')
            queries.append(f'"{company_name}" "{company_domain}" site:linkedin.com/in{title_part}')
        queries.append(f'site:linkedin.com/in "{company_name}"{domain_part}{title_part}{team_part}')

    results: list[dict] = []
    seen_urls: set[str] = set()
    for query in dict.fromkeys(queries):
        for item in await _run_serper_query(query, limit):
            parsed = brave_search_client._parse_linkedin_result(
                _serper_item_to_brave_item(item),
                company_name,
            )
            if not parsed:
                continue
            url = parsed.get("linkedin_url") or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            results.append(_relabel_result(parsed, source="serper_search"))
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
    title_clause = brave_search_client._quoted_or_clause(title_hints, limit=2)
    if title_clause:
        queries.extend(
            f'site:linkedin.com/in "{name}" "{company_name}" {title_clause}'
            for name in ordered_names
        )

    keyword_clause = brave_search_client._quoted_or_clause(team_keywords, limit=2)
    if keyword_clause:
        queries.extend(
            f'site:linkedin.com/in "{name}" "{company_name}" {keyword_clause}'
            for name in ordered_names
        )

    results: list[dict] = []
    seen_urls: set[str] = set()
    for query in queries:
        for item in await _run_serper_query(query, max(1, min(limit, 5))):
            parsed = brave_search_client._parse_linkedin_result(
                _serper_item_to_brave_item(item),
                company_name,
            )
            if not parsed:
                continue
            linkedin_url = parsed.get("linkedin_url") or ""
            if linkedin_url and linkedin_url in seen_urls:
                continue
            profile_data = dict(parsed.get("profile_data") or {})
            profile_data["linkedin_backfill_query"] = query
            profile_data["linkedin_backfill_result_url"] = linkedin_url
            parsed["profile_data"] = profile_data
            results.append(_relabel_result(parsed, source="serper_search"))
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
    team_part = f' "{team_keywords[0]}"' if team_keywords else ""

    identity_part = ""
    if public_identity_terms:
        quoted_terms = [f'"{term}"' for term in public_identity_terms[:2] if term]
        if quoted_terms:
            identity_part = " " + " OR ".join(quoted_terms)

    queries: list[str] = []
    role_hint = brave_search_client._public_role_hint(titles)
    for slug in public_identity_terms[:2] if public_identity_terms else []:
        clean_slug = (slug or "").strip().lower()
        if not clean_slug:
            continue
        scoped_hint = role_hint or ""
        if not scoped_hint:
            # Use first batch of titles as fallback hint
            first_clause = brave_search_client._quoted_or_clause(
                (titles or [])[:2], limit=2,
            )
            scoped_hint = first_clause
        if scoped_hint:
            queries.append(f'site:theorg.com/org/{clean_slug} "{company_name}" {scoped_hint}')
        else:
            queries.append(f'site:theorg.com/org/{clean_slug} "{company_name}"')

    # Build one public-web query per title batch to cover the full list
    for batch in _title_batches(titles, batch_size=2):
        title_clause = brave_search_client._quoted_or_clause(batch, limit=2)
        title_part = f" {title_clause}" if title_clause else ""
        queries.append(
            f'("{company_name}"{title_part}{team_part}{identity_part}) '
            '(site:theorg.com OR site:linkedin.com/posts OR site:clay.earth OR site:contactout.com)'
        )

    items: list[dict] = []
    seen_urls: set[str] = set()
    for query in dict.fromkeys(queries):
        for item in await _run_serper_query(query, limit):
            clean_url = brave_search_client._clean_profile_url(item.get("link", ""))
            key = clean_url or f'{item.get("title", "")}|{item.get("snippet", "")}'
            if key in seen_urls:
                continue
            seen_urls.add(key)
            items.append(item)

    results: list[dict] = []
    for item in items:
        parsed = brave_search_client._parse_public_people_result(
            _serper_item_to_brave_item(item),
            company_name,
        )
        if parsed:
            results.append(_relabel_result(parsed, source="serper_public_web"))
    return results[:limit]


async def search_hiring_team(
    company_name: str,
    job_title: str,
    team_keywords: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    team_part = f' "{team_keywords[0]}"' if team_keywords else ""
    query = f'site:linkedin.com/jobs "{company_name}" "{job_title}"{team_part}'

    results: list[dict] = []
    for item in await _run_serper_query(query, 5):
        parsed_results = brave_search_client._parse_hiring_team_result(
            _serper_item_to_brave_item(item),
            company_name,
        )
        for parsed in parsed_results:
            results.append(_relabel_result(parsed, source="serper_hiring_team"))
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
    results: list[dict] = []
    for item in await _run_serper_query(query, limit):
        url = (item.get("link") or "").strip()
        if not url:
            continue
        results.append(
            {
                "url": re.split(r"[?#]", url)[0].rstrip("/"),
                "title": (item.get("title") or "").strip(),
                "description": (item.get("snippet") or "").strip(),
                "source": "serper_public_web",
            }
        )
    return results[:limit]
