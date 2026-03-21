"""Firecrawl client wrapper for corroboration pages."""

import httpx

from app.config import settings


async def scrape_url(url: str, *, timeout_seconds: int = 20) -> dict | None:
    """Fetch a public page via Firecrawl and return normalized content."""
    if not settings.firecrawl_base_url:
        return None

    headers = {}
    if settings.firecrawl_api_key:
        headers["Authorization"] = f"Bearer {settings.firecrawl_api_key}"

    base_url = settings.firecrawl_base_url.rstrip("/")
    payload = {"url": url, "formats": ["markdown", "html"]}

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for endpoint in ("/v2/scrape", "/v1/scrape"):
            try:
                resp = await client.post(f"{base_url}{endpoint}", json=payload, headers=headers)
            except httpx.HTTPError:
                return None

            if resp.status_code == 404:
                continue
            if resp.status_code in (401, 403, 429):
                return None

            try:
                resp.raise_for_status()
            except httpx.HTTPError:
                return None

            data = resp.json()
            page = data.get("data", data)
            markdown = page.get("markdown") or ""
            html = page.get("html") or ""
            content = markdown or html or ""
            if not content:
                return None

            return {
                "url": url,
                "title": (page.get("metadata") or {}).get("title", "") or page.get("title", ""),
                "content": content,
                "markdown": markdown,
                "html": html,
                "retrieval_method": "firecrawl",
            }

    return None
