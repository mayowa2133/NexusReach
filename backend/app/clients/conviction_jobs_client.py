"""Client for Conviction startup jobs board."""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.utils.startup_jobs import text_matches_query

logger = logging.getLogger(__name__)

BASE_URL = "https://www.conviction.com/jobs"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_DATA_RE = re.compile(r"const\s+unsortedData\s*=\s*(\[[\s\S]*?\]);", re.IGNORECASE)


def parse_jobs_page_html(html_content: str, *, query: str | None = None) -> list[dict]:
    match = _DATA_RE.search(html_content or "")
    if not match:
        return []

    payload = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', match.group(1))
    payload = re.sub(r",(\s*[}\]])", r"\1", payload)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Failed to decode Conviction jobs payload")
        return []

    startups: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        company_name = str(item.get("company") or "").strip()
        career_url = str(item.get("link") or "").strip()
        roles = []
        for role in item.get("roles") or []:
            if not isinstance(role, dict):
                continue
            title = str(role.get("title") or "").strip()
            location = str(role.get("location") or "").strip()
            if query and not text_matches_query(text=f"{title} {location}", query=query):
                continue
            if not title:
                continue
            roles.append({"title": title, "location": location or None})
        if not company_name or not career_url or not roles:
            continue
        startups.append({
            "company_name": company_name,
            "career_url": career_url,
            "roles": roles,
            "source": "conviction",
        })
    return startups


async def fetch_conviction_startups(query: str | None = None) -> list[dict]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(BASE_URL, headers=REQUEST_HEADERS)
        response.raise_for_status()
    return parse_jobs_page_html(response.text, query=query)
