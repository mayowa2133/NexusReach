"""Public-footprint miner for non-technical leaders.

Non-technical leaders (sales, marketing, finance, ...) rarely leave a code
trail, but they DO leave an editorial one: they speak at conferences, guest on
podcasts, byline articles, and put "Title @ Company" in their X/Twitter bios.
This miner runs a small set of SERP queries against those surfaces and
extracts named leaders by exact title - a complement to the company-website
roster (own-domain) and news/PR quotes (appointment announcements).

Bounded (a few queries), Redis-cached, and fails soft to an empty list.
"""

from __future__ import annotations

import logging
import re

from app.clients import brave_search_client, searxng_search_client, search_cache_client

logger = logging.getLogger(__name__)

CACHE_PREFIX = "people:public_footprint:v1:"
CACHE_TTL_SECONDS = 14 * 86400
MAX_CANDIDATES = 6

_LEADER_TITLE_TOKEN = (
    r"(?:Chief[A-Za-z ]*Officer|C[EOTMFR]O|Chief of Staff|Senior Vice President|"
    r"Vice President|VP(?: of [A-Za-z &]+)?|Head of [A-Za-z &]+|Director(?: of [A-Za-z &]+)?|"
    r"President|Partner|Managing Director|General Manager)"
)
_NAME = r"[A-Z][a-z]+(?:\s+[A-Z][a-z.'-]+){1,2}"

_QUOTE_PATTERNS = [
    re.compile(rf"({_NAME}),\s+(?:the\s+)?({_LEADER_TITLE_TOKEN})"),
    re.compile(rf"({_LEADER_TITLE_TOKEN})(?:\s+at[^,]+)?,\s+({_NAME})"),
    re.compile(rf"({_NAME})\s+[-–|·]\s+({_LEADER_TITLE_TOKEN})"),
]


def _extract_people(text: str, company_token: str) -> list[tuple[str, str]]:
    if company_token and company_token not in text.lower():
        return []
    found: list[tuple[str, str]] = []
    for pattern in _QUOTE_PATTERNS:
        for m in pattern.finditer(text):
            g1, g2 = m.group(1).strip(), m.group(2).strip()
            if re.search(r"chief|director|president|vp|vice|head|partner|officer|manager", g1, re.I):
                title, name = g1, g2
            else:
                name, title = g1, g2
            name = _clean_name(name)
            title = title.strip(" .,;:-\u2013\u2014")
            if name and " " in name and len(name) <= 40:
                found.append((name, title))
    return found


def _clean_name(name: str) -> str:
    """Strip stray leading/trailing punctuation a greedy regex may capture."""
    return (name or "").strip().strip(".,;:-\u2013\u2014'\"").strip()


async def _run_query(query: str, num: int) -> list[dict]:
    """SearXNG primary, Brave fallback - both generic web search."""
    try:
        results = await searxng_search_client._run_searxng_query(query, num)
    except Exception:
        results = []
    if not results:
        try:
            results = await brave_search_client._run_brave_query(query, num)
        except Exception:
            results = []
    return results or []


async def discover_public_footprint_leaders(
    company_name: str,
    title_hints: list[str] | None = None,
    *,
    limit: int = MAX_CANDIDATES,
) -> list[dict]:
    """Find leaders via speaker/podcast/byline mentions and X/Twitter bios.

    Returns candidate dicts (source="public_footprint") with name + title.
    Cached by company; fail-soft to [].
    """
    if not company_name:
        return []
    cache_key = CACHE_PREFIX + company_name.lower().strip()
    try:
        cached = await search_cache_client.get_json(cache_key)
        if cached is not None:
            return [_shape(c, company_name) for c in cached][:limit]
    except Exception:
        pass

    titles = title_hints[:2] if title_hints else []
    title_clause = " OR ".join(f'"{t}"' for t in titles) if titles else ""
    queries = [
        f'"{company_name}" {title_clause} (podcast OR webinar OR keynote OR conference OR panel)'.strip(),
        f'(site:x.com OR site:twitter.com) "{company_name}" {title_clause}'.strip(),
    ]

    company_token = company_name.lower().split()[0] if company_name else ""
    raw: list[dict] = []
    seen: set[str] = set()
    for query in queries:
        for item in await _run_query(query, 6):
            text = f"{item.get('title', '')}. {item.get('content', '')}"
            for name, title in _extract_people(text, company_token):
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                raw.append({"name": name, "title": title, "url": item.get("url")})
                if len(raw) >= limit:
                    break
            if len(raw) >= limit:
                break
        if len(raw) >= limit:
            break

    try:
        await search_cache_client.set_json(cache_key, raw, ttl_seconds=CACHE_TTL_SECONDS)
    except Exception:
        pass
    return [_shape(c, company_name) for c in raw][:limit]


def _shape(entry: dict, company_name: str) -> dict:
    return {
        "full_name": entry["name"],
        "title": entry["title"],
        "source": "public_footprint",
        "snippet": f"Public footprint (talk/byline/bio) as {entry['title']} at {company_name}.",
        "linkedin_url": "",
        "_public_footprint_leader": True,
        "_employment_status": "current",
        "profile_data": {
            "company_match_confidence": "weak_signal",
            "public_footprint": True,
            "public_footprint_url": entry.get("url"),
        },
    }
