"""The Org traversal for bucket-aware candidate expansion."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.clients import theorg_client
from app.config import settings
from app.models.company import Company
from app.utils.job_context import JobContext

RECRUITER_TITLE_KEYWORDS = (
    "recruiter",
    "talent acquisition",
    "talent partner",
    "sourcer",
    "recruiting",
    "people ops",
    "people operations",
    "human resources",
)
MANAGER_TITLE_KEYWORDS = (
    "manager",
    "director",
    "head",
    "vice president",
    "vp",
    "lead",
)
DIRECTOR_PLUS_KEYWORDS = (
    "director",
    "head",
    "vice president",
    "vp",
    "chief",
)

TEAM_KEYWORDS_BY_BUCKET = {
    "recruiters": (
        "human resources",
        "talent",
        "people",
        "recruit",
        "university",
        "early career",
    ),
}
TEAM_KEYWORDS_BY_DEPARTMENT = {
    "engineering": (
        "engineering",
        "software development",
        "software",
        "product and engineering",
        "product and technology",
        "platform",
    ),
    "data_science": (
        "data",
        "analytics",
        "business intelligence",
        "data science",
        "machine learning",
        "business systems",
    ),
    "product_management": ("product", "strategy"),
    "human_resources": ("human resources", "talent", "people"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _parse_cached_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_cache_fresh(entry: dict | None, *, ttl_hours: int) -> bool:
    if not entry:
        return False
    cached_at = _parse_cached_at(entry.get("cached_at"))
    if not cached_at:
        return False
    return cached_at >= _now() - timedelta(hours=ttl_hours)


def _company_hints(company: Company) -> dict:
    return company.identity_hints if isinstance(company.identity_hints, dict) else {}


def _theorg_cache(company: Company) -> dict:
    hints = _company_hints(company)
    cache = hints.get("theorg")
    if not isinstance(cache, dict):
        cache = {}
    hints["theorg"] = cache
    company.identity_hints = hints
    return cache


def _is_useful_org_page(parsed: dict | None) -> bool:
    if not parsed:
        return False
    if parsed.get("teams") or parsed.get("leaders"):
        return True
    return bool(parsed.get("company_name"))


def _ordered_public_identity_slugs(slugs: list[str] | None) -> list[str]:
    candidates = list(slugs or [])
    return sorted(
        candidates,
        key=lambda slug: (0 if slug.endswith("hq") else 1, -len(slug), slug),
    )


def _title_haystack(value: str | None) -> str:
    return (value or "").lower()


def _is_recruiter(title: str | None) -> bool:
    haystack = _title_haystack(title)
    return any(keyword in haystack for keyword in RECRUITER_TITLE_KEYWORDS)


def _is_manager(title: str | None) -> bool:
    haystack = _title_haystack(title)
    return any(keyword in haystack for keyword in MANAGER_TITLE_KEYWORDS)


def _is_director_plus(title: str | None) -> bool:
    haystack = _title_haystack(title)
    return any(keyword in haystack for keyword in DIRECTOR_PLUS_KEYWORDS)


def _is_peer(title: str | None) -> bool:
    return not _is_recruiter(title) and not _is_manager(title)


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    seen: set[str] = set()
    ordered: list[dict] = []
    for candidate in candidates:
        profile_data = candidate.get("profile_data") or {}
        public_url = profile_data.get("public_url") or ""
        key = public_url or f"{candidate.get('full_name')}|{candidate.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate)
    return ordered


def _team_score(team: dict, *, bucket: str, context: JobContext | None) -> tuple[int, int] | None:
    haystack = " ".join(
        part for part in [team.get("slug", ""), team.get("name", ""), team.get("description", "")] if part
    ).lower()
    keywords = TEAM_KEYWORDS_BY_BUCKET.get(bucket)
    if bucket in {"hiring_managers", "peers"}:
        department = context.department if context else "engineering"
        keywords = TEAM_KEYWORDS_BY_DEPARTMENT.get(
            department,
            TEAM_KEYWORDS_BY_DEPARTMENT["engineering"],
        )

    if not keywords:
        return None

    for rank, keyword in enumerate(keywords):
        if keyword in haystack:
            return (rank, -(team.get("member_count") or 0))
    return None


def _select_team_refs(org_page: dict, *, bucket: str, context: JobContext | None) -> list[dict]:
    scored = []
    for team in org_page.get("teams", []):
        score = _team_score(team, bucket=bucket, context=context)
        if score is None:
            continue
        scored.append((score, team))
    scored.sort(key=lambda item: item[0])
    return [team for _, team in scored]


async def _get_org_page(company: Company) -> dict | None:
    cache = _theorg_cache(company)
    org_entry = cache.get("org")
    if _is_cache_fresh(org_entry, ttl_hours=settings.theorg_cache_ttl_hours):
        parsed = org_entry.get("parsed")
        if _is_useful_org_page(parsed):
            return parsed

    for slug in _ordered_public_identity_slugs(company.public_identity_slugs):
        page = await theorg_client.fetch_page(
            f"https://theorg.com/org/{slug}",
            timeout_seconds=settings.theorg_timeout_seconds,
        )
        parsed = theorg_client.parse_org_page(page or {})
        if not _is_useful_org_page(parsed):
            continue
        cache["org"] = {
            "cached_at": _iso_now(),
            "parsed": parsed,
        }
        company.identity_hints = _company_hints(company)
        return parsed
    return None


async def _get_team_page(company: Company, team_ref: dict) -> dict | None:
    cache = _theorg_cache(company)
    team_pages = cache.setdefault("team_pages", {})
    team_slug = team_ref.get("slug")
    entry = team_pages.get(team_slug)
    if _is_cache_fresh(entry, ttl_hours=settings.theorg_cache_ttl_hours):
        return entry.get("parsed")

    page = await theorg_client.fetch_page(
        team_ref["url"],
        timeout_seconds=settings.theorg_timeout_seconds,
    )
    parsed = theorg_client.parse_team_page(page or {})
    if not parsed:
        return None
    team_pages[team_slug] = {
        "cached_at": _iso_now(),
        "parsed": parsed,
    }
    company.identity_hints = _company_hints(company)
    return parsed


async def _get_person_page(company: Company, public_url: str) -> dict | None:
    cache = _theorg_cache(company)
    person_pages = cache.setdefault("person_pages", {})
    entry = person_pages.get(public_url)
    if _is_cache_fresh(entry, ttl_hours=settings.theorg_cache_ttl_hours):
        return entry.get("parsed")

    page = await theorg_client.fetch_page(
        public_url,
        timeout_seconds=settings.theorg_timeout_seconds,
    )
    parsed = theorg_client.parse_person_page(page or {})
    if not parsed:
        return None
    person_pages[public_url] = {
        "cached_at": _iso_now(),
        "parsed": parsed,
    }
    company.identity_hints = _company_hints(company)
    return parsed


def _bucket_candidate(person: dict, *, bucket: str, context: JobContext | None) -> bool:
    title = person.get("title") or ""
    if bucket == "recruiters":
        return _is_recruiter(title)
    if bucket == "hiring_managers":
        if not _is_manager(title):
            return False
        if context and getattr(context, "early_career", False) and _is_director_plus(title):
            return False
        return True
    if _is_recruiter(title):
        return False
    if _is_director_plus(title):
        return False
    if context and getattr(context, "early_career", False) and _is_manager(title):
        return False
    return _is_peer(title)


def _truncate_grouped(grouped: dict[str, list[dict]]) -> dict[str, list[dict]]:
    flattened = []
    for bucket, people in grouped.items():
        for person in people:
            flattened.append((bucket, person))
    flattened = flattened[: settings.theorg_max_harvested_people]

    limited = {"recruiters": [], "hiring_managers": [], "peers": []}
    for bucket, person in flattened:
        limited[bucket].append(person)
    return limited


async def discover_theorg_candidates(
    company: Company,
    *,
    company_name: str,
    context: JobContext | None,
    current_counts: dict[str, int],
) -> dict[str, list[dict]]:
    """Traverse trusted The Org pages to expand underfilled candidate buckets."""
    if not settings.theorg_traversal_enabled:
        return {"recruiters": [], "hiring_managers": [], "peers": []}
    if not company.public_identity_slugs:
        return {"recruiters": [], "hiring_managers": [], "peers": []}

    org_page = await _get_org_page(company)
    if not org_page:
        return {"recruiters": [], "hiring_managers": [], "peers": []}

    grouped = {"recruiters": [], "hiring_managers": [], "peers": []}
    visited_team_urls: set[str] = set()
    manager_seeds: list[dict] = []

    bucket_needs = {
        "recruiters": current_counts.get("recruiters", 0) < 2,
        "hiring_managers": current_counts.get("hiring_managers", 0) < 2,
        "peers": current_counts.get("peers", 0) < 2,
    }

    ordered_team_refs: list[tuple[str, dict]] = []
    for bucket in ("recruiters", "hiring_managers", "peers"):
        if not bucket_needs[bucket] and bucket != "peers":
            continue
        for team_ref in _select_team_refs(org_page, bucket=bucket, context=context)[: settings.theorg_max_team_pages]:
            ordered_team_refs.append((bucket, team_ref))

    unique_team_refs: list[dict] = []
    seen_team_urls: set[str] = set()
    for _, team_ref in ordered_team_refs:
        if team_ref["url"] in seen_team_urls:
            continue
        seen_team_urls.add(team_ref["url"])
        unique_team_refs.append(team_ref)
        if len(unique_team_refs) >= settings.theorg_max_team_pages:
            break

    for team_ref in unique_team_refs:
        if team_ref["url"] in visited_team_urls:
            continue
        visited_team_urls.add(team_ref["url"])
        parsed_team = await _get_team_page(company, team_ref)
        if not parsed_team:
            continue
        for person in parsed_team.get("people", []):
            title = person.get("title") or ""
            if bucket_needs["recruiters"] and _bucket_candidate(person, bucket="recruiters", context=context):
                grouped["recruiters"].append(person)
            if bucket_needs["hiring_managers"] and _bucket_candidate(person, bucket="hiring_managers", context=context):
                grouped["hiring_managers"].append(person)
                if len(manager_seeds) < settings.theorg_max_manager_pages:
                    manager_seeds.append(person)
            if bucket_needs["peers"] and _bucket_candidate(person, bucket="peers", context=context):
                grouped["peers"].append(person)
            if (
                bucket_needs["peers"]
                and _is_manager(title)
                and len(manager_seeds) < settings.theorg_max_manager_pages
                and person not in manager_seeds
            ):
                manager_seeds.append(person)

    for seed in manager_seeds[: settings.theorg_max_manager_pages]:
        public_url = ((seed.get("profile_data") or {}).get("public_url") or "").strip()
        if not public_url:
            continue
        parsed_person = await _get_person_page(company, public_url)
        if not parsed_person:
            continue
        person = parsed_person.get("person")
        if person and bucket_needs["hiring_managers"] and _bucket_candidate(person, bucket="hiring_managers", context=context):
            grouped["hiring_managers"].append(person)
        if bucket_needs["peers"]:
            grouped["peers"].extend(
                report
                for report in parsed_person.get("reports", [])
                if _bucket_candidate(report, bucket="peers", context=context)
            )

    for bucket, people in grouped.items():
        grouped[bucket] = _dedupe_candidates(people)

    grouped = _truncate_grouped(grouped)
    cache = _theorg_cache(company)
    cache["last_harvest"] = {
        "cached_at": _iso_now(),
        "results": deepcopy(grouped),
    }
    company.identity_hints = _company_hints(company)
    return grouped
