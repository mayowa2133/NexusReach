"""Search-provider router with sequential fallback and Redis caching."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.clients import (
    brave_search_client,
    searxng_search_client,
    google_search_client,
    search_cache_client,
    serper_search_client,
    tavily_search_client,
)
from app.config import settings

logger = logging.getLogger(__name__)

ProviderFetcher = Callable[..., Awaitable[list[dict]]]


def _provider_order(raw: str, *, allowed: set[str], default: list[str]) -> list[str]:
    parsed = [value.strip() for value in (raw or "").split(",") if value.strip()]
    ordered: list[str] = []
    for provider in parsed or default:
        if provider in allowed and provider not in ordered:
            ordered.append(provider)
    return ordered or list(default)


def _cache_key(family: str, provider: str, params: dict[str, Any]) -> str:
    payload = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"search:{family}:{provider}:{digest}"


async def _cached_provider_results(
    family: str,
    provider: str,
    fetcher: ProviderFetcher,
    params: dict[str, Any],
) -> tuple[list[dict], bool]:
    key = _cache_key(family, provider, params)
    cached = await search_cache_client.get_json(key)
    if isinstance(cached, list):
        return cached, True

    try:
        results = await fetcher(**params)
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.warning(
            "search provider failed",
            extra={"provider": provider, "family": family, "error": str(exc)},
        )
        return [], False

    await search_cache_client.set_json(key, results, ttl_seconds=settings.search_cache_ttl_seconds)
    return results, False


def _annotate_result(
    item: dict,
    *,
    provider: str,
    family: str,
    fallback_depth: int,
    cache_hit: bool,
) -> dict:
    annotated = dict(item)
    if any(key in annotated for key in ("full_name", "linkedin_url", "profile_data")):
        profile_data = dict(annotated.get("profile_data") or {})
        profile_data["search_provider"] = provider
        profile_data["search_query_family"] = family
        profile_data["search_fallback_depth"] = fallback_depth
        profile_data["search_cache_hit"] = cache_hit
        annotated["profile_data"] = profile_data
        return annotated

    annotated["search_provider"] = provider
    annotated["search_query_family"] = family
    annotated["search_fallback_depth"] = fallback_depth
    annotated["search_cache_hit"] = cache_hit
    return annotated


def _result_identity(family: str, item: dict) -> str:
    if family == "search_employment_sources":
        return f'url:{item.get("url", "")}'

    linkedin_url = item.get("linkedin_url") or ""
    if linkedin_url:
        return f"linkedin:{linkedin_url}"

    profile_data = item.get("profile_data") or {}
    public_url = profile_data.get("public_url") if isinstance(profile_data, dict) else ""
    if public_url:
        return f"public:{public_url}"

    full_name = (item.get("full_name") or "").strip().lower()
    title = (item.get("title") or "").strip().lower()
    return f"name:{full_name}|title:{title}"


def _dedupe_results(family: str, results: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in results:
        key = _result_identity(family, item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


async def _run_family(
    family: str,
    *,
    providers: dict[str, ProviderFetcher],
    order: list[str],
    min_results: int,
    limit: int,
    params: dict[str, Any],
) -> list[dict]:
    aggregated: list[dict] = []
    for depth, provider in enumerate(order):
        fetcher = providers.get(provider)
        if fetcher is None:
            continue
        results, cache_hit = await _cached_provider_results(family, provider, fetcher, params)
        if not results:
            logger.info(
                "search provider empty",
                extra={"provider": provider, "family": family, "fallback_depth": depth, "cache_hit": cache_hit},
            )
            continue

        annotated = [
            _annotate_result(
                item,
                provider=provider,
                family=family,
                fallback_depth=depth,
                cache_hit=cache_hit,
            )
            for item in results
        ]
        aggregated = _dedupe_results(family, aggregated + annotated)
        logger.info(
            "search provider hit",
            extra={
                "provider": provider,
                "family": family,
                "fallback_depth": depth,
                "cache_hit": cache_hit,
                "result_count": len(results),
                "aggregate_count": len(aggregated),
            },
        )
        if len(aggregated) >= min_results:
            break

    return aggregated[:limit]


async def search_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    limit: int = 10,
    min_results: int = 1,
    company_domain: str | None = None,
) -> list[dict]:
    providers: dict[str, ProviderFetcher] = {
        "searxng": searxng_search_client.search_people,
        "serper": serper_search_client.search_people,
        "brave": brave_search_client.search_people,
        "google_cse": google_search_client.search_people,
    }
    order = _provider_order(
        settings.search_linkedin_provider_order,
        allowed=set(providers),
        default=["searxng", "serper", "brave", "google_cse"],
    )
    return await _run_family(
        "search_people",
        providers=providers,
        order=order,
        min_results=max(1, min_results),
        limit=limit,
        params={
            "company_name": company_name,
            "titles": titles,
            "team_keywords": team_keywords,
            "limit": limit,
            "company_domain": company_domain,
        },
    )


async def search_exact_linkedin_profile(
    full_name: str,
    company_name: str,
    *,
    name_variants: list[str] | None = None,
    title_hints: list[str] | None = None,
    team_keywords: list[str] | None = None,
    limit: int = 3,
) -> list[dict]:
    providers: dict[str, ProviderFetcher] = {
        "searxng": searxng_search_client.search_exact_linkedin_profile,
        "brave": brave_search_client.search_exact_linkedin_profile,
        "serper": serper_search_client.search_exact_linkedin_profile,
        "google_cse": google_search_client.search_exact_linkedin_profile,
    }
    order = _provider_order(
        settings.search_exact_linkedin_provider_order,
        allowed=set(providers),
        default=["searxng", "brave", "serper", "google_cse"],
    )
    return await _run_family(
        "search_exact_linkedin_profile",
        providers=providers,
        order=order,
        min_results=1,
        limit=limit,
        params={
            "full_name": full_name,
            "company_name": company_name,
            "name_variants": name_variants,
            "title_hints": title_hints,
            "team_keywords": team_keywords,
            "limit": limit,
        },
    )


async def search_public_people(
    company_name: str,
    titles: list[str] | None = None,
    team_keywords: list[str] | None = None,
    public_identity_terms: list[str] | None = None,
    limit: int = 5,
    min_results: int = 1,
) -> list[dict]:
    providers: dict[str, ProviderFetcher] = {
        "searxng": searxng_search_client.search_public_people,
        "serper": serper_search_client.search_public_people,
        "brave": brave_search_client.search_public_people,
        "tavily": tavily_search_client.search_public_people,
    }
    order = _provider_order(
        settings.search_public_provider_order,
        allowed=set(providers),
        default=["searxng", "serper", "brave", "tavily"],
    )
    return await _run_family(
        "search_public_people",
        providers=providers,
        order=order,
        min_results=max(1, min_results),
        limit=limit,
        params={
            "company_name": company_name,
            "titles": titles,
            "team_keywords": team_keywords,
            "public_identity_terms": public_identity_terms,
            "limit": limit,
        },
    )


async def search_hiring_team(
    company_name: str,
    job_title: str,
    team_keywords: list[str] | None = None,
    limit: int = 5,
    min_results: int = 1,
) -> list[dict]:
    providers: dict[str, ProviderFetcher] = {
        "searxng": searxng_search_client.search_hiring_team,
        "serper": serper_search_client.search_hiring_team,
        "brave": brave_search_client.search_hiring_team,
    }
    order = _provider_order(
        settings.search_hiring_team_provider_order,
        allowed=set(providers),
        default=["searxng", "serper", "brave"],
    )
    return await _run_family(
        "search_hiring_team",
        providers=providers,
        order=order,
        min_results=max(1, min_results),
        limit=limit,
        params={
            "company_name": company_name,
            "job_title": job_title,
            "team_keywords": team_keywords,
            "limit": limit,
        },
    )


async def search_employment_sources(
    full_name: str,
    company_name: str,
    *,
    company_domain: str | None = None,
    public_identity_terms: list[str] | None = None,
    limit: int = 5,
    min_results: int = 1,
) -> list[dict]:
    providers: dict[str, ProviderFetcher] = {
        "tavily": tavily_search_client.search_employment_sources,
        "searxng": searxng_search_client.search_employment_sources,
        "serper": serper_search_client.search_employment_sources,
        "brave": brave_search_client.search_employment_sources,
    }
    order = _provider_order(
        settings.search_employment_provider_order,
        allowed=set(providers),
        default=["tavily", "searxng", "serper", "brave"],
    )
    return await _run_family(
        "search_employment_sources",
        providers=providers,
        order=order,
        min_results=max(1, min_results),
        limit=limit,
        params={
            "full_name": full_name,
            "company_name": company_name,
            "company_domain": company_domain,
            "public_identity_terms": public_identity_terms,
            "limit": limit,
        },
    )
