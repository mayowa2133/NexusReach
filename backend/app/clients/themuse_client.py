"""The Muse public jobs API client — free, keyless, all-industry.

The Muse (``themuse.com/developers/api/v2``) is the cross-industry breadth source
that backstops JSearch/Adzuna for every non-tech occupation. It is free and works
without an API key (a free key only raises the rate limit); it fails soft to ``[]``
on any error, quota, or timeout, exactly like the other niche-board clients.

The public API filters by ``category`` (a fixed Muse taxonomy), ``level``,
``location``, and ``company`` — there is no free-text keyword param. So a free-text
query (e.g. a saved "Registered Nurse" search) is mapped to one or more Muse
categories via the occupation taxonomy, then the raw category results are
token-filtered back down to the query so a specific saved search stays relevant.
Occupation-routed discovery passes the category directly and skips the token filter
(occupation tagging + the feed's occupation filter handle relevance downstream, the
same way curated ATS-board jobs are handled).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

import httpx

from app.config import settings
from app.services.occupation_taxonomy import OCCUPATIONS, classify_title

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.themuse.com/api/public/jobs"
_PER_PAGE = 20  # The Muse returns 20 results per page (not configurable).
_MAX_PAGES_PER_CATEGORY = 5  # Hard ceiling so one occupation can't fan out forever.
_REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NexusReach/1.0)"}


# NexusReach occupation key -> The Muse category names. The Muse taxonomy is
# coarser than ours, so several occupations share a category and some map to two.
# These names are the exact, live-verified Muse category strings (a wrong name
# silently returns zero results, so do not guess — verify against the API).
MUSE_CATEGORY_BY_OCCUPATION: dict[str, tuple[str, ...]] = {
    "software_engineering": ("Software Engineering",),
    "machine_learning_ai": ("Data and Analytics", "Software Engineering"),
    "data_engineer": ("Data and Analytics", "Software Engineering"),
    "data_analyst": ("Data and Analytics",),
    "cybersecurity": ("Software Engineering",),
    "product_management": ("Product Management",),
    "project_management": ("Project Management",),
    "marketing": ("Advertising and Marketing",),
    "sales": ("Sales", "Account Management"),
    "customer_service_support": ("Customer Service", "Account Management"),
    "creatives_design": ("Design and UX", "Media, PR, and Communications"),
    "arts_entertainment": ("Media, PR, and Communications",),
    "accounting_finance": ("Accounting and Finance",),
    "consulting": ("Business Operations", "Management"),
    "business_analyst": ("Business Operations", "Data and Analytics"),
    "human_resources": ("Human Resources and Recruitment",),
    "management_executive": ("Management",),
    "legal_compliance": ("Legal Services",),
    "healthcare": ("Healthcare",),
    "education_training": ("Education",),
    "engineering_development": ("Science and Engineering",),
    "supply_chain": ("Business Operations", "Transportation and Logistics"),
    "public_sector_government": ("Business Operations",),
}


def _categories_for_query(query: str | None) -> list[str]:
    """Derive Muse categories from a free-text query via title classification."""
    keys = classify_title(query) if query else []
    categories: list[str] = []
    for key in keys:
        for cat in MUSE_CATEGORY_BY_OCCUPATION.get(key, ()):
            if cat not in categories:
                categories.append(cat)
    return categories


# Function words + seniority qualifiers that survive the length filter but carry
# no occupational signal — stripped so a word like "senior" can never become a
# distinctive token (it appears across many occupations' title seeds).
_STOPWORDS = frozenset({
    "and", "the", "for", "with", "you", "our", "your",
    "senior", "junior", "lead", "staff", "principal", "entry", "intern",
    "internship", "mid", "level", "grad", "new", "associate",
})


def _tokenize(text: str) -> set[str]:
    return {
        t
        for t in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(t) > 2 and t not in _STOPWORDS
    }


def _build_distinctive_vocab() -> dict[str, frozenset[str]]:
    """Per-occupation set of *distinctive* title tokens, derived from the taxonomy.

    Each occupation's vocabulary is the tokens of its aliases, default queries, and
    peer/manager title seeds. We then keep only tokens whose document frequency
    across occupations is low — so generic role words ("manager", "director",
    "analyst", "senior") that appear in many occupations are dropped automatically,
    while distinctive words ("marketing", "nurse", "attorney", "procurement",
    "electrical") survive. This is the relevance vocabulary used to gate The Muse's
    coarse categories without any hand-maintained stopword list.
    """
    per_occ_tokens: dict[str, set[str]] = {}
    doc_freq: dict[str, int] = {}
    for occ in OCCUPATIONS:
        tokens: set[str] = set()
        for phrase in (
            *occ.aliases,
            *occ.default_search_queries,
            *occ.peer_title_seeds,
            *occ.manager_title_seeds,
        ):
            tokens |= _tokenize(phrase)
        per_occ_tokens[occ.key] = tokens
        for tok in tokens:
            doc_freq[tok] = doc_freq.get(tok, 0) + 1

    # A token is distinctive if it identifies at most a few occupations. Tuned so
    # cross-functional words ("manager"/"director"/"analyst"/"engineer") fall out
    # but genuine role nouns stay.
    max_doc_freq = 4
    return {
        key: frozenset(t for t in tokens if doc_freq[t] <= max_doc_freq)
        for key, tokens in per_occ_tokens.items()
    }


_DISTINCTIVE_VOCAB: dict[str, frozenset[str]] = _build_distinctive_vocab()


def _relevant_to_occupation(title: str, occupation: str) -> bool:
    """True when the title shares a distinctive token with the occupation.

    Off-category Muse noise (e.g. "Data Center Chiller Serviceman" under a
    business-analyst search) shares no distinctive token and is dropped, so the
    discover pipeline never mislabels it via the occupation's fallback tag.
    """
    vocab = _DISTINCTIVE_VOCAB.get(occupation)
    if not vocab:
        return True
    return bool(_tokenize(title) & vocab)


def _title_matches_query(title: str, query: str | None) -> bool:
    """True when the title shares a meaningful token with a free-text query."""
    q_tokens = _tokenize(query) if query else set()
    if not q_tokens:
        return True
    return bool(_tokenize(title) & q_tokens)


def _normalize_muse_job(job: dict) -> dict | None:
    title = (job.get("name") or "").strip()
    if not title:
        return None
    company = job.get("company") or {}
    company_name = (company.get("name") or "").strip()
    refs = job.get("refs") or {}
    url = (refs.get("landing_page") or "").strip()

    locations = [
        (loc.get("name") or "").strip()
        for loc in (job.get("locations") or [])
        if loc.get("name")
    ]
    location = locations[0] if locations else "Unknown"
    remote = any(
        kw in loc.lower()
        for loc in locations
        for kw in ("remote", "flexible")
    )

    category_tags = [
        (cat.get("name") or "").strip().lower()
        for cat in (job.get("categories") or [])
        if cat.get("name")
    ]
    level_tags = [
        (lvl.get("name") or "").strip()
        for lvl in (job.get("levels") or [])
        if lvl.get("name")
    ]

    return {
        "external_id": f"themuse_{job.get('id', '')}",
        "title": title,
        "company_name": company_name,
        "location": location,
        "remote": remote,
        "url": url,
        "apply_url": url or None,
        "description": job.get("contents") or "",
        "employment_type": (job.get("type") or "").strip(),
        # publication_date is a precise ISO datetime, so this yields a real
        # posted_ts (sub-day precision) per the posting-time precision contract.
        "posted_at": job.get("publication_date") or None,
        "salary": "",
        "tags": [*category_tags, *(t.lower() for t in level_tags)],
        "source": "themuse",
    }


async def _fetch_category_page(
    client: httpx.AsyncClient,
    *,
    category: str | None,
    page: int,
) -> tuple[list[dict], int]:
    """Return (results, page_count) for one Muse page. Fails soft to ([], 0)."""
    params: dict[str, str | int] = {"page": page}
    if category:
        params["category"] = category
    if settings.themuse_api_key:
        params["api_key"] = settings.themuse_api_key
    try:
        resp = await client.get(_BASE_URL, params=params, headers=_REQUEST_HEADERS)
    except httpx.HTTPError as exc:
        logger.warning("The Muse fetch failed (category=%s): %s", category, exc)
        return [], 0
    if resp.status_code != 200:
        # 429 (rate limited) and 4xx/5xx all fail soft — discovery continues
        # on the other sources, exactly like an over-quota aggregator.
        if resp.status_code == 429:
            logger.warning("The Muse rate-limited (category=%s)", category)
        return [], 0
    try:
        data = resp.json()
    except ValueError:
        return [], 0
    return data.get("results") or [], int(data.get("page_count") or 0)


async def _fetch_category(
    client: httpx.AsyncClient,
    *,
    category: str | None,
    max_results: int,
    keep: Callable[[dict], bool],
) -> list[dict]:
    """Fetch + normalize one category, paging until ``max_results`` jobs pass.

    ``keep`` is applied per normalized job so we page deeper when a relevance
    gate is filtering hard, instead of returning a thin under-filled batch.
    """
    collected: list[dict] = []
    for page in range(1, _MAX_PAGES_PER_CATEGORY + 1):
        results, page_count = await _fetch_category_page(
            client, category=category, page=page
        )
        for raw in results:
            job = _normalize_muse_job(raw)
            if job is None or not keep(job):
                continue
            collected.append(job)
        if len(collected) >= max_results:
            break
        if not results or (page_count and page >= page_count):
            break
    return collected[:max_results]


async def search_themuse(
    query: str | None = None,
    *,
    categories: list[str] | None = None,
    occupation: str | None = None,
    location: str | None = None,
    remote_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Search The Muse, returning normalized raw-job dicts. Fails soft to ``[]``.

    Category resolution order: explicit ``categories`` > ``occupation`` map >
    ``query`` classification > broad (no category).

    Relevance gating keeps Muse's coarse categories honest:
    - occupation path: keep titles sharing a distinctive token with the
      occupation (so off-target category noise isn't mislabeled).
    - free-text query path: keep titles sharing a token with the query (so a
      specific saved search stays on-topic).
    """
    resolved_categories: list[str]
    if categories:
        resolved_categories = list(categories)
    elif occupation:
        resolved_categories = list(MUSE_CATEGORY_BY_OCCUPATION.get(occupation, ()))
    else:
        resolved_categories = _categories_for_query(query)

    def keep(job: dict) -> bool:
        if remote_only and not job["remote"]:
            return False
        if occupation:
            return _relevant_to_occupation(job["title"], occupation)
        return _title_matches_query(job["title"], query)

    # No category resolved → one broad page so the source is never a hard zero.
    fetch_targets: list[str | None] = resolved_categories or [None]
    per_category = max(_PER_PAGE, (limit + len(fetch_targets) - 1) // len(fetch_targets))

    async with httpx.AsyncClient(timeout=20) as client:
        batches = await asyncio.gather(
            *(
                _fetch_category(
                    client, category=cat, max_results=per_category, keep=keep
                )
                for cat in fetch_targets
            )
        )

    seen_ids: set[str] = set()
    normalized: list[dict] = []
    for batch in batches:
        for job in batch:
            if job["external_id"] in seen_ids:
                continue
            seen_ids.add(job["external_id"])
            normalized.append(job)
            if len(normalized) >= limit:
                return normalized
    return normalized
