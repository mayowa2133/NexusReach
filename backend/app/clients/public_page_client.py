"""Generic public-page retrieval with free-first fallbacks."""

from __future__ import annotations

import html as html_lib
import logging
import re
from urllib.parse import urlparse

import httpx

from app.clients import crawl4ai_client, firecrawl_client, jina_reader_client
from app.config import settings
from app.utils.url_safety import is_safe_public_url_async, safe_get

logger = logging.getLogger(__name__)

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
    """Fetch a public page directly over HTTP (SSRF-safe — audit pass-2 P4)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    # Validate the host and every redirect hop so a page URL can't reach an
    # internal/metadata target. The module's own client is passed so it stays
    # mockable in tests.
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
            resp = await safe_get(url, headers=headers, client=client)
    except httpx.HTTPError:
        return None
    if resp is None or resp.status_code >= 400:
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


def _log_retrieval_outcome(
    url: str,
    page: dict | None,
    *,
    direct_sufficient: bool,
    jina_rescued: bool,
) -> None:
    """Emit one structured line per ``fetch_page`` so Jina's real fallback
    hit-rate is measurable from production logs without any new infrastructure.

    Grep ``public_page.retrieval`` over a traffic window, then:
      - jina rescue rate      = count(jina_rescued=True) / total
      - among direct failures = count(jina_rescued=True) / count(direct_sufficient=False)
    ``method`` is the provider that produced the returned page (``none`` when the
    whole waterfall failed). Only the host is logged — never the path or query —
    so no page-specific or sensitive URL data lands in logs.

    REVIEW 2026-08-06 (~2 weeks of traffic): decide whether Jina Reader earns its
    keep. If ``jina_rescued=True`` is ~never seen (direct/crawl4ai already win
    everywhere it's tried), scrap it: set NEXUSREACH_JINA_READER_ENABLED=false to
    disable instantly, or revert the jina_reader_client wiring for full removal.
    Added 2026-07-23 because live n=2 sampling was inconclusive — see the
    jina-reader-value-review memory.
    """
    method = page.get("retrieval_method", "none") if page else "none"
    try:
        host = urlparse(url).hostname or "?"
    except ValueError:
        host = "?"
    logger.info(
        "public_page.retrieval host=%s method=%s direct_sufficient=%s jina_rescued=%s",
        host,
        method,
        direct_sufficient,
        jina_rescued,
    )


async def fetch_page(
    url: str,
    *,
    timeout_seconds: int = 20,
    include_direct: bool = True,
    allow_firecrawl: bool = True,
) -> dict | None:
    """Fetch a public page using free-first retrieval with optional Firecrawl fallback."""
    # Crawl4AI and Firecrawl perform their own network requests. Admit the URL
    # once before any provider is allowed to see it, including fallback paths.
    if not await is_safe_public_url_async(url):
        return None

    direct_page = None
    if include_direct:
        direct_page = await fetch_direct_page(url, timeout_seconds=timeout_seconds)
        if _is_page_sufficient(direct_page):
            _log_retrieval_outcome(url, direct_page, direct_sufficient=True, jina_rescued=False)
            return direct_page

    # Jina Reader proxies the fetch from its own infrastructure — our only
    # outbound connection is to the fixed public host r.jina.ai, never to the
    # target — so unlike the renderers below it adds no SSRF surface and needs no
    # egress-policy gate. Keyless and free, it's the first fallback and runs even
    # in the default config where the rendered stack is disabled.
    jina_page = await jina_reader_client.fetch_url(url, timeout_seconds=timeout_seconds)
    if jina_page:
        jina_page["fallback_used"] = include_direct and direct_page is not None
        if _is_page_sufficient(jina_page):
            _log_retrieval_outcome(url, jina_page, direct_sufficient=False, jina_rescued=True)
            return jina_page

    # These renderers do not expose a connection-level IP pinning hook. Do not
    # enable their separate fetch stacks until infrastructure has an egress
    # policy that denies private, link-local, and metadata address ranges.
    if not (
        settings.rendered_page_fetch_enabled
        and settings.rendered_page_egress_policy_enforced
    ):
        result = jina_page or direct_page
        _log_retrieval_outcome(url, result, direct_sufficient=False, jina_rescued=False)
        return result

    crawl4ai_page = await crawl4ai_client.fetch_url(
        url,
        timeout_seconds=timeout_seconds,
    )
    if crawl4ai_page:
        crawl4ai_page["fallback_used"] = bool(
            (include_direct and direct_page is not None) or jina_page is not None
        )
        if _is_page_sufficient(crawl4ai_page):
            _log_retrieval_outcome(url, crawl4ai_page, direct_sufficient=False, jina_rescued=False)
            return crawl4ai_page

    if allow_firecrawl:
        firecrawl_page = await firecrawl_client.scrape_url(
            url,
            timeout_seconds=timeout_seconds,
        )
        if firecrawl_page:
            firecrawl_page["fallback_used"] = bool(
                (include_direct and direct_page is not None)
                or jina_page is not None
                or crawl4ai_page is not None
            )
            _log_retrieval_outcome(url, firecrawl_page, direct_sufficient=False, jina_rescued=False)
            return firecrawl_page

    result = direct_page or jina_page or crawl4ai_page
    _log_retrieval_outcome(url, result, direct_sufficient=False, jina_rescued=False)
    return result
