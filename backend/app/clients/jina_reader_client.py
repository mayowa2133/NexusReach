"""Jina Reader client — keyless, free public-page-to-text fallback.

Jina Reader (``https://r.jina.ai/<url>``) fetches a page from Jina's own
infrastructure and returns clean markdown/text, so it recovers JS-rendered pages
a plain ``httpx`` GET can't.

SSRF posture (why this differs from Crawl4AI/Firecrawl): our only outbound
connection is to the single fixed public host ``r.jina.ai`` — never to the
target URL, which Jina resolves and fetches on its own network. So it adds no
SSRF surface from *our* egress and needs no ``rendered_page_egress_policy``
gate; it runs even in the default config where the rendered stack is disabled.
We still validate the target is a public URL before handing it to Jina so we
never ask a third party to fetch an internal/metadata address on our behalf.

Free and keyless — an optional API key only raises the rate limit. Fails soft to
``None`` on any error, matching the other page-fetch fallbacks. Target URLs are
sent to a third party (Jina), so it is disable-able via ``jina_reader_enabled``.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.config import settings
from app.utils.url_safety import is_safe_public_url_async


def _is_linkedin_host(url: str) -> bool:
    """True for linkedin.com and any subdomain (www./ca./…)."""
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


async def fetch_url(url: str, *, timeout_seconds: int = 20) -> dict | None:
    """Fetch a public page via Jina Reader and return normalized content."""
    if not settings.jina_reader_enabled:
        return None
    # Never route LinkedIn through Jina. The product deliberately avoids
    # server-side LinkedIn fetching (the legal risk that killed Proxycurl); LinkedIn
    # evidence comes only from the dedicated public_profile_client SERP path. This
    # guard lives at the client so no caller — the fetch_page chain or a direct
    # call — can turn this fallback into a backdoor LinkedIn scraper.
    if _is_linkedin_host(url):
        return None
    # Defense in depth: never ask Jina to fetch an internal/metadata target.
    # fetch_page already validates once up front; this keeps a direct call safe.
    if not await is_safe_public_url_async(url):
        return None

    base = settings.jina_reader_base_url.rstrip("/")
    # Jina takes the readable target URL as the path (documented usage is a bare
    # prepend, e.g. ``r.jina.ai/https://example.com/x?y=1``); do NOT percent-
    # encode it or Jina can't recover the target.
    endpoint = f"{base}/{url}"
    headers = {
        "Accept": "application/json",
        "X-Return-Format": "markdown",
    }
    if settings.jina_reader_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_reader_api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.get(endpoint, headers=headers)
    except httpx.HTTPError:
        return None

    if resp.status_code >= 400:
        return None

    try:
        payload = resp.json()
    except ValueError:
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None

    markdown = (data.get("content") or "").strip()
    if not markdown:
        return None

    return {
        "url": data.get("url") or url,
        "title": (data.get("title") or "").strip(),
        "content": markdown,
        "markdown": markdown,
        "html": data.get("html") or "",
        "retrieval_method": "jina_reader",
    }
