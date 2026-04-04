"""Client for a16z Speedrun startup companies."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://speedrun-be.a16z.com/api/companies/companies/"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def parse_companies_payload(payload: dict) -> list[dict]:
    results = payload.get("results") or []
    companies: list[dict] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        website_url = str(item.get("website_url") or "").strip()
        name = str(item.get("name") or "").strip()
        if not name or not website_url:
            continue
        location_parts = [
            str(item.get("city") or "").strip(),
            str(item.get("state") or "").strip(),
            str(item.get("country") or "").strip(),
        ]
        location = ", ".join(part for part in location_parts if part) or None
        companies.append({
            "company_name": name,
            "website_url": website_url,
            "location": location,
            "source": "a16z_speedrun",
        })
    return companies


async def fetch_speedrun_companies(limit: int | None = None) -> list[dict]:
    companies: list[dict] = []
    offset = 0
    page_size = 50

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        while True:
            response = await client.get(
                BASE_URL,
                params={"limit": page_size, "offset": offset, "ordering": "name"},
                headers=REQUEST_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
            page_companies = parse_companies_payload(payload)
            if not page_companies:
                break
            companies.extend(page_companies)
            if limit is not None and len(companies) >= limit:
                return companies[:limit]
            if not payload.get("next"):
                break
            offset += page_size

    return companies[:limit] if limit is not None else companies
