"""Generic public-page retrieval with free-first fallbacks."""

from __future__ import annotations

import html as html_lib
import re

import httpx

from app.clients import crawl4ai_client, firecrawl_client

TITLE_RE = re.compile(r"<title>(.*?)</title>", flags=re.IGNORECASE | re.DOTALL)
SCRIPT_STYLE_RE = re.compile(r"<(?:script|style)[^>]*>.*?</(?:script|style)>", flags=re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
INSUFFICIENT_CONTENT_PATTERNS = (
    "enable javascript",
    "javascript is required",
    "javascript is disabled",
    "verify you are human",
    "attention required",
    "captcha",
    "access denied",
)


def _extract_title(html: str) -> str:
    match = TITLE_RE.search(html or "")
    if not match:
        return ""
    return html_lib.unescape(match.group(1)).strip()


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    without_scripts = SCRIPT_STYLE_RE.sub(" ", html)
    without_tags = TAG_RE.sub(" ", without_scripts)
    return WHITESPACE_RE.sub(" ", html_lib.unescape(without_tags)).strip()


def _normalize_page(
    *,
    url: str,
    title: str,
    html: str,
    markdown: str,
    content: str,
    retrieval_method: str,
    fallback_used: bool,
) -> dict | None:
    normalized_content = (content or "").strip()
    normalized_html = (html or "").strip()
    normalized_markdown = (markdown or "").strip()
    if not normalized_content and normalized_html:
        normalized_content = _html_to_text(normalized_html)
    if not normalized_content:
        return None
    return {
        "url": url,
        "title": title.strip(),
        "content": normalized_content,
        "html": normalized_html,
        "markdown": normalized_markdown,
        "retrieval_method": retrieval_method,
        "fallback_used": fallback_used,
    }


def _is_page_sufficient(page: dict | None) -> bool:
    if not page:
        return False
    content = (page.get("content") or "").strip()
    html = page.get("html") or ""
    if "__NEXT_DATA__" in html:
        return True
    if not content:
        return False
    lowered = " ".join(
        part for part in [(page.get("title") or ""), content[:1000], html[:1000]] if part
    ).lower()
    if any(pattern in lowered for pattern in INSUFFICIENT_CONTENT_PATTERNS):
        return False
    return len(content) >= 120 or bool(page.get("title"))


async def fetch_direct_page(url: str, *, timeout_seconds: int = 20) -> dict | None:
    """Fetch a public page directly over HTTP."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = (resp.headers.get("content-type") or "").lower()
    body = resp.text
    html = body if "html" in content_type or "<html" in body.lower() else ""
    title = _extract_title(html) if html else ""
    content = _html_to_text(html) if html else body.strip()
    return _normalize_page(
        url=str(resp.url),
        title=title,
        html=html,
        markdown="",
        content=content,
        retrieval_method="direct",
        fallback_used=False,
    )


async def fetch_page(
    url: str,
    *,
    timeout_seconds: int = 20,
    include_direct: bool = True,
    allow_firecrawl: bool = True,
) -> dict | None:
    """Fetch a public page using free-first retrieval with optional Firecrawl fallback."""
    direct_page = None
    if include_direct:
        direct_page = await fetch_direct_page(url, timeout_seconds=timeout_seconds)
        if _is_page_sufficient(direct_page):
            return direct_page

    crawl4ai_page = await crawl4ai_client.fetch_url(
        url,
        timeout_seconds=timeout_seconds,
    )
    if crawl4ai_page:
        crawl4ai_page["fallback_used"] = include_direct and direct_page is not None
        if _is_page_sufficient(crawl4ai_page):
            return crawl4ai_page

    if allow_firecrawl:
        firecrawl_page = await firecrawl_client.scrape_url(
            url,
            timeout_seconds=timeout_seconds,
        )
        if firecrawl_page:
            firecrawl_page["fallback_used"] = bool(
                (include_direct and direct_page is not None) or crawl4ai_page is not None
            )
            return firecrawl_page

    if direct_page:
        return direct_page
    return crawl4ai_page
