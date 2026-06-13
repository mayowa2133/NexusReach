"""Company-website leadership parser - the non-technical analog of GitHub-team.

Technical people leave a public work artifact (code) that names the real team.
Non-technical people don't - but their employer almost always publishes its
leadership on its own website (an /about, /leadership, or /team page). That
page is the company's own published roster across every function (sales,
marketing, finance, legal, ...), so it is the highest-recall non-technical
source for the long tail of companies The Org does not index.

The page is on the company's own domain, so a person named there is
company-verified by construction. Everything here is bounded (a few path
probes, one LLM extraction), Redis-cached, and fails soft to an empty list.
"""

from __future__ import annotations

import json
import logging
import re

from app.clients import (
    brave_search_client,
    llm_client,
    public_page_client,
    search_cache_client,
    searxng_search_client,
)

logger = logging.getLogger(__name__)

LEADERS_CACHE_PREFIX = "people:company_site_leaders:v1:"
LEADERS_CACHE_TTL_SECONDS = 30 * 86400
MAX_LEADERS = 12
FETCH_TIMEOUT_SECONDS = 12

# Most common leadership/team page paths, most specific first. Probing stops at
# the first page that looks like a leadership page.
_COMMON_PATHS = (
    "/leadership",
    "/about/leadership",
    "/company/leadership",
    "/team",
    "/our-team",
    "/about/team",
    "/people",
    "/about-us",
    "/about",
    "/who-we-are",
    "/company",
    # Domain-specific people directories (legal / education / healthcare /
    # professional services) - these publish the full staff, not just C-level.
    "/attorneys",
    "/our-attorneys",
    "/lawyers",
    "/professionals",
    "/our-people",
    "/faculty",
    "/faculty-staff",
    "/directory",
    "/staff",
    "/providers",
    "/our-providers",
    "/find-a-doctor",
    "/physicians",
    "/our-doctors",
)

_TEAM_PAGE_SIGNALS = (
    "ceo", "chief", "founder", "co-founder", "president", "vp ", "vice president",
    "head of", "director", "leadership", "our team", "management team",
    "executive", "leadership team",
    # directory signals (legal / education / healthcare / professional services)
    "partner", "attorney", "counsel", "professor", "faculty", "physician",
    "md,", "m.d.", "nurse", "dean", "principal", "manager",
)

_LEADER_TITLE_RE = re.compile(
    r"\b(chief|c[eotmfr]o\b|founder|co-founder|president|vp\b|vice president|head of|director|"
    r"general manager|managing director|partner|principal|lead\b)\b",
    re.IGNORECASE,
)

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract a company's leadership/team from the text of its own website "
    "page. Return ONLY a JSON array of objects {\"name\": str, \"title\": str} "
    "for people whose name AND role are literally stated on the page. Include "
    "executives, VPs, directors, heads of function, and managers. Do NOT invent "
    "anyone; if the page lists no named people, return []. No prose, no fences."
)


def _looks_like_team_page(page: dict | None) -> bool:
    if not page:
        return False
    text = (page.get("text") or page.get("content") or "").lower()
    if len(text) < 200:
        return False
    hits = sum(1 for sig in _TEAM_PAGE_SIGNALS if sig in text)
    return hits >= 3


def _cache_key(domain: str) -> str:
    return LEADERS_CACHE_PREFIX + domain.lower().strip()


async def _search_team_page_url(company_name: str, domain: str) -> str | None:
    """Find the leadership/team/directory page URL via SERP, restricted to the
    company's own domain. Catches non-standard paths (e.g. /en/people.html)
    that fixed-path probing misses."""
    root = domain.removeprefix("www.")
    query = f'site:{root} (leadership OR "our team" OR "our people" OR attorneys OR faculty OR providers OR directory)'
    try:
        results = await searxng_search_client._run_searxng_query(query, 6)
    except Exception:
        results = []
    if not results:
        try:
            results = await brave_search_client._run_brave_query(query, 6)
        except Exception:
            results = []
    for item in results:
        url = item.get("url") or ""
        if root in url:
            return url
    return None


async def _fetch_team_page(domain: str, company_name: str = "") -> tuple[str, str] | None:
    """Return (url, text) for the company's leadership/team page, or None.

    Tries a SERP-discovered URL first (handles non-standard paths), then falls
    back to probing common paths on the domain. Note: pages whose people list
    is JS-rendered yield little static text and are skipped - the SERP-based
    news/footprint miners cover those companies instead.
    """
    domain = domain.strip().lower().rstrip("/")
    if not domain or "." not in domain:
        return None
    base = domain if domain.startswith("http") else f"https://{domain.removeprefix('www.')}"

    candidate_urls: list[str] = []
    if company_name:
        serp_url = await _search_team_page_url(company_name, domain)
        if serp_url:
            candidate_urls.append(serp_url)
    candidate_urls.extend(base + path for path in _COMMON_PATHS)

    for url in candidate_urls:
        try:
            page = await public_page_client.fetch_page(url, timeout_seconds=FETCH_TIMEOUT_SECONDS)
        except Exception:
            continue
        if _looks_like_team_page(page):
            return url, (page.get("text") or page.get("content") or "")
    return None


async def _extract_leaders(text: str, company_name: str) -> list[dict]:
    """LLM-extract {name, title} leaders from page text. Fail-soft to []."""
    snippet = text[:8000]
    try:
        result = await llm_client.generate_message(
            system_prompt=_EXTRACTION_SYSTEM_PROMPT,
            user_prompt=f"Company: {company_name}\n\nPage text:\n{snippet}",
            max_tokens=900,
        )
        raw = result.get("draft") or ""
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end <= start:
            return []
        parsed = json.loads(raw[start : end + 1])
    except Exception:
        logger.warning("company-site leader extraction failed for %s", company_name, exc_info=True)
        return []

    leaders: list[dict] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        title = (item.get("title") or "").strip()
        key = name.lower()
        if not name or " " not in name or not title or key in seen:
            continue
        seen.add(key)
        leaders.append({"name": name, "title": title})
        if len(leaders) >= MAX_LEADERS:
            break
    return leaders


async def discover_company_site_leaders(
    company_name: str,
    domain: str | None,
    *,
    origin_url: str | None = None,
) -> list[dict]:
    """Return leadership candidates from the company's own website.

    Each candidate carries ``_company_site_leader=True`` and strong-signal
    confidence (the page is the company's own domain). The occupation gate
    downstream filters by function and ranking orders them.
    """
    if not domain:
        return []
    cache_key = _cache_key(domain)
    cached = None
    try:
        cached = await search_cache_client.get_json(cache_key)
    except Exception:
        cached = None

    if cached is None:
        fetched = await _fetch_team_page(domain, company_name)
        if not fetched:
            try:
                await search_cache_client.set_json(cache_key, [], ttl_seconds=LEADERS_CACHE_TTL_SECONDS)
            except Exception:
                pass
            return []
        page_url, text = fetched
        leaders = await _extract_leaders(text, company_name)
        payload = [{"name": ldr["name"], "title": ldr["title"], "url": page_url} for ldr in leaders]
        try:
            await search_cache_client.set_json(cache_key, payload, ttl_seconds=LEADERS_CACHE_TTL_SECONDS)
        except Exception:
            pass
        cached = payload

    candidates: list[dict] = []
    for entry in cached or []:
        name = entry.get("name")
        title = entry.get("title")
        if not name or not title:
            continue
        candidates.append(
            {
                "full_name": name,
                "title": title,
                "source": "company_site",
                "snippet": f"Listed on {company_name}'s leadership/team page as {title}.",
                "linkedin_url": "",
                "_company_site_leader": True,
                "_employment_status": "current",
                "profile_data": {
                    "company_match_confidence": "strong_signal",
                    "company_site_leader": True,
                    "company_site_url": entry.get("url") or origin_url,
                },
            }
        )
    return candidates
