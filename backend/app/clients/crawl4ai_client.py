"""Crawl4AI client wrapper for public LinkedIn verification."""

import asyncio


async def fetch_profile(linkedin_url: str, *, timeout_seconds: int = 20) -> dict | None:
    """Fetch a public LinkedIn page via Crawl4AI.

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
                crawler.arun(url=linkedin_url),
                timeout=timeout_seconds,
            )
    except Exception:
        return None

    if not getattr(result, "success", False):
        return None

    markdown = getattr(result, "markdown", "")
    if hasattr(markdown, "raw_markdown"):
        content = markdown.raw_markdown
    elif isinstance(markdown, str):
        content = markdown
    else:
        content = str(markdown or "")

    if not content:
        content = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
    if not content:
        return None

    return {
        "url": linkedin_url,
        "title": getattr(result, "title", "") or "",
        "content": content,
    }
