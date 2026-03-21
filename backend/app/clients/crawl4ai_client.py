"""Crawl4AI client wrapper for public page retrieval."""

import asyncio


def _normalize_result(url: str, result: object) -> dict | None:
    markdown = getattr(result, "markdown", "")
    if hasattr(markdown, "raw_markdown"):
        markdown_content = markdown.raw_markdown
    elif isinstance(markdown, str):
        markdown_content = markdown
    else:
        markdown_content = str(markdown or "")

    html = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
    content = markdown_content or html or ""
    if not content:
        return None

    return {
        "url": url,
        "title": getattr(result, "title", "") or "",
        "content": content,
        "markdown": markdown_content,
        "html": html,
        "retrieval_method": "crawl4ai",
    }


async def fetch_url(url: str, *, timeout_seconds: int = 20) -> dict | None:
    """Fetch a public page via Crawl4AI.

    Returns a normalized payload or ``None`` when Crawl4AI is unavailable
    or the page cannot be fetched.
    """
    try:
        from crawl4ai import AsyncWebCrawler  # type: ignore
    except ImportError:
        return None

    try:
        async with AsyncWebCrawler() as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url),
                timeout=timeout_seconds,
            )
    except Exception:
        return None

    if not getattr(result, "success", False):
        return None

    return _normalize_result(url, result)


async def fetch_profile(linkedin_url: str, *, timeout_seconds: int = 20) -> dict | None:
    """Fetch a public LinkedIn page via Crawl4AI."""
    return await fetch_url(linkedin_url, timeout_seconds=timeout_seconds)
