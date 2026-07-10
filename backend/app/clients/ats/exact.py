"""Exact-job page fetching pipeline with provider-specific fetchers."""

from __future__ import annotations

from typing import Callable

import httpx

from app.clients import crawl4ai_client, firecrawl_client
from app.config import settings
from app.utils.url_safety import is_safe_public_url, is_safe_public_url_async, safe_get
from app.clients.ats.boards import search_workable
from app.clients.ats.html import _extract_title
from app.clients.ats.normalize import _job_richness_score, _normalize_apple_job, _normalize_exact_page, _normalize_generic_exact_job, _normalize_icims_job, _normalize_workday_job, _workday_page_matches
from app.clients.ats.urls import ParsedATSJobURL


class ExactJobFetchError(ValueError):
    """Raised when an exact job URL can be resolved but not extracted."""


async def _fetch_direct_exact_page(
    url: str,
    *,
    timeout_seconds: int = 20,
    allow_empty_content: bool = False,
) -> dict | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    # SSRF-safe fetch: validates the host and every redirect hop so a public URL
    # can't bounce to an internal/metadata target (audit pass-2 P4). The module's
    # own client is passed so it stays mockable in tests.
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            resp = await safe_get(url, headers=headers, client=client)
    except httpx.HTTPError:
        return None
    if resp is None or resp.status_code >= 400:
        return None

    body = resp.text
    content_type = (resp.headers.get("content-type") or "").lower()
    html = body if "html" in content_type or "<html" in body.lower() else ""

    return _normalize_exact_page(
        url=str(resp.url),
        title=_extract_title(html) if html else "",
        html=html,
        markdown="",
        content="" if html else body.strip(),
        retrieval_method="direct",
        fallback_used=False,
        allow_empty_content=allow_empty_content,
    )


async def _fetch_exact_page_candidates(
    parsed: ParsedATSJobURL,
    *,
    allow_empty_content: bool = False,
) -> list[dict]:
    url = parsed.canonical_url or ""
    pages: list[dict] = []

    direct_page = await _fetch_direct_exact_page(
        url,
        timeout_seconds=20,
        allow_empty_content=allow_empty_content,
    )
    if direct_page:
        pages.append(direct_page)

    # crawl4ai and firecrawl do their own fetch + DNS resolution, bypassing
    # safe_get's per-hop SSRF guard. Re-validate the host immediately before
    # handing them the URL, mirroring _probe_workday_job_redirect — otherwise a
    # rebound/internal host that safe_get would refuse could still be reached
    # through these fetchers (SSRF). This narrows the DNS-rebinding TOCTOU window
    # to the same level as the direct path.
    if settings.rendered_page_fetch_enabled and await is_safe_public_url_async(url):
        crawl4ai_page = await crawl4ai_client.fetch_url(url, timeout_seconds=20)
        if crawl4ai_page:
            crawl4ai_page["fallback_used"] = bool(pages)
            pages.append(crawl4ai_page)

        firecrawl_page = await firecrawl_client.scrape_url(url, timeout_seconds=20)
        if firecrawl_page:
            firecrawl_page["fallback_used"] = bool(pages)
            pages.append(firecrawl_page)

    return pages


async def _probe_workday_job_redirect(parsed: ParsedATSJobURL) -> str | None:
    url = parsed.canonical_url or ""
    if not is_safe_public_url(url):  # SSRF guard (audit pass-2 P4)
        return None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError:
        return None

    if resp.status_code not in {301, 302, 303, 307, 308}:
        return None

    location = str(resp.headers.get("location") or "").strip().lower()
    if not location:
        return "redirected"
    if "wday/drs/outage" in location or "community.workday.com/maintenance-page" in location:
        return "outage"
    return "redirected"


async def _fetch_exact_job_with_normalizer(
    parsed: ParsedATSJobURL,
    *,
    normalizer: Callable[[ParsedATSJobURL, dict], dict | None],
    error_message: str,
    allow_empty_content: bool = False,
) -> list[dict]:
    pages = await _fetch_exact_page_candidates(parsed, allow_empty_content=allow_empty_content)
    if not pages:
        raise ExactJobFetchError("Could not read the job posting page.")

    # Collect all successful normalizations, pick the richest one.
    candidates: list[dict] = []
    for page in pages:
        job = normalizer(parsed, page)
        if job:
            candidates.append(job)

    if not candidates:
        raise ExactJobFetchError(error_message)

    # When only one candidate or first is already rich, fast-path.
    if len(candidates) == 1:
        return [candidates[0]]

    best = max(candidates, key=_job_richness_score)
    return [best]


async def _fetch_workable_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    if not parsed.company_slug or not parsed.external_id:
        raise ExactJobFetchError("Could not resolve the Workable job URL.")
    return await search_workable(
        parsed.company_slug,
        job_shortcode=parsed.external_id.removeprefix("wk_"),
    )


async def _fetch_apple_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    return await _fetch_exact_job_with_normalizer(
        parsed,
        normalizer=_normalize_apple_job,
        error_message="We found the Apple job page, but couldn't extract enough job details from it.",
        allow_empty_content=True,
    )


async def _fetch_workday_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    redirect_status = await _probe_workday_job_redirect(parsed)
    pages = await _fetch_exact_page_candidates(parsed, allow_empty_content=True)
    candidate_pages = [page for page in pages if _workday_page_matches(parsed, page)]

    if not candidate_pages:
        if redirect_status == "outage":
            raise ExactJobFetchError("Workday is currently unavailable for this job posting.")
        if redirect_status == "redirected":
            raise ExactJobFetchError(
                "Workday redirected away from the job details, so we couldn't extract the posting."
            )
        raise ExactJobFetchError("Could not read the job posting page.")

    for page in candidate_pages:
        job = _normalize_workday_job(parsed, page)
        if job:
            return [job]

    raise ExactJobFetchError("We found the Workday job page, but couldn't extract enough job details from it.")


async def _fetch_generic_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    return await _fetch_exact_job_with_normalizer(
        parsed,
        normalizer=lambda parsed_job, page: _normalize_generic_exact_job(page, parsed_job),
        error_message="We found the page, but couldn't extract enough job details from it.",
        allow_empty_content=True,
    )


async def _fetch_icims_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    return await _fetch_exact_job_with_normalizer(
        parsed,
        normalizer=_normalize_icims_job,
        error_message="We found the iCIMS job page, but couldn't extract enough job details from it.",
        allow_empty_content=True,
    )
