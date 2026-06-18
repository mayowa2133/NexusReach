"""LinkedIn profile backfill matching and enrichment for people discovery."""

import asyncio
import logging


from app.clients import public_profile_client, search_router_client
from app.utils.job_context import (
    JobContext,
)

from app.services.people.classify import _classify_person
from app.services.people.company_match import PUBLIC_WEB_SOURCES, _classify_employment_status, _linkedin_company_match, _trusted_public_match
from app.services.people.context import _location_match_rank
from app.services.people.identity import _identity_tokens, _linkedin_backfill_name_variants, _name_match_score, _normalize_identity, _public_profile_url
from app.services.people.theorg_recovery import _title_recovery_metadata
from app.services.people.titles import _is_manager_like, _is_recruiter_like, _title_is_weak
logger = logging.getLogger(__name__)


def _linkedin_backfill_metadata(
    data: dict,
    *,
    status: str,
    confidence: int | None = None,
    source: str = "search_router",
    strategy: str | None = None,
) -> dict:
    profile_data = dict(data.get("profile_data") or {})
    profile_data["linkedin_backfill_status"] = status
    profile_data["linkedin_backfill_source"] = source
    if confidence is not None:
        profile_data["linkedin_backfill_confidence"] = confidence
    if strategy:
        profile_data["linkedin_backfill_strategy"] = strategy
    return profile_data




def _linkedin_role_match(candidate: dict, *, bucket: str) -> bool:
    title = candidate.get("title", "") or ""
    snippet = candidate.get("snippet", "") or ""
    person_type = _classify_person(title, source=candidate.get("source", ""), snippet=snippet)
    if bucket == "recruiters":
        return person_type == "recruiter" and (_is_recruiter_like(title) or _is_recruiter_like(snippet))
    if bucket == "hiring_managers":
        return person_type == "hiring_manager" and (_is_manager_like(title) or _is_manager_like(snippet))
    return person_type == "peer"


def _linkedin_title_match_score(
    candidate: dict,
    match: dict,
    *,
    company_name: str,
    bucket: str,
) -> int:
    candidate_title = candidate.get("title", "") or ""
    profile_data = match.get("profile_data") or {}
    result_title = profile_data.get("linkedin_result_title", "") or ""
    texts = [match.get("title", "") or "", result_title, match.get("snippet", "") or ""]

    if candidate_title and not _title_is_weak(candidate_title, company_name):
        normalized_candidate = _normalize_identity(candidate_title)
        if any(normalized_candidate and normalized_candidate in _normalize_identity(text) for text in texts if text):
            return 4

        candidate_tokens = {
            token
            for token in _identity_tokens(candidate_title)
            if token not in {"senior", "staff", "principal", "global", "technical"}
        }
        if candidate_tokens:
            best_overlap = 0
            for text in texts:
                text_tokens = set(_identity_tokens(text))
                if not text_tokens:
                    continue
                best_overlap = max(best_overlap, len(candidate_tokens & text_tokens))
            if best_overlap >= 2:
                return 3

    if bucket == "recruiters" and any(_is_recruiter_like(text) for text in texts):
        return 2
    if bucket == "hiring_managers" and any(_is_manager_like(text) for text in texts):
        return 2
    if bucket == "peers" and any(_classify_person(str(text), snippet=match.get("snippet", "")) == "peer" for text in texts if text):
        return 1
    return 0


def _linkedin_backfill_search_titles(candidate: dict, *, bucket: str, company_name: str, context: JobContext | None = None) -> list[str]:
    titles: list[str] = []
    current_title = (candidate.get("title") or "").strip()
    if current_title and not _title_is_weak(current_title, company_name):
        titles.append(current_title)

    if bucket == "recruiters":
        titles.extend(
            [
                "talent acquisition partner",
                "technical recruiter",
                "recruiter",
            ]
        )
    elif bucket == "hiring_managers":
        dept = context.department if context else ""
        if dept == "product_management":
            titles.extend(
                [
                    "group product manager",
                    "senior product manager",
                    "director of product management",
                    "head of product",
                ]
            )
        elif dept == "design":
            titles.extend(
                [
                    "design manager",
                    "head of design",
                    "senior design manager",
                ]
            )
        else:
            titles.extend(
                [
                    "engineering manager",
                    "software engineering manager",
                    "director engineering",
                    "senior director engineering",
                ]
            )
    elif bucket == "peers":
        dept = context.department if context else ""
        if dept == "product_management":
            titles.extend(["product manager", "associate product manager", "technical program manager"])
        elif dept == "design":
            titles.extend(["product designer", "ux designer", "ui designer"])
        else:
            titles.extend(["software engineer", "senior software engineer"])

    ordered: list[str] = []
    seen: set[str] = set()
    for title in titles:
        normalized = _normalize_identity(title)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(title)
    return ordered[:4]


def _linkedin_backfill_team_keywords(candidate: dict, *, bucket: str) -> list[str]:
    profile_data = candidate.get("profile_data") or {}
    keywords: list[str] = []

    team_name = str(profile_data.get("theorg_team_name") or "").strip()
    if team_name:
        keywords.append(team_name)

    team_slug = str(profile_data.get("theorg_team_slug") or "").replace("-", " ").strip()
    if team_slug:
        keywords.append(team_slug)

    relationship = str(profile_data.get("theorg_relationship") or "").strip()
    if relationship:
        keywords.append(relationship.replace("_", " "))

    if bucket == "recruiters":
        keywords.extend(["talent acquisition", "recruiting", "early careers"])
    elif bucket == "hiring_managers":
        keywords.extend(["engineering", "software", "platform"])

    ordered: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        normalized = _normalize_identity(keyword)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(keyword)
    return ordered[:3]


def _choose_linkedin_backfill_match(
    candidate: dict,
    matches: list[dict],
    *,
    company_name: str,
    bucket: str,
) -> tuple[dict | None, int | None, str]:
    scored_matches: list[tuple[int, int, dict]] = []
    for match in matches:
        name_score = _name_match_score(candidate.get("full_name"), match.get("full_name"))
        if name_score < 90:
            continue
        if not _linkedin_company_match(match, company_name):
            continue
        if not _linkedin_role_match(match, bucket=bucket):
            continue
        title_score = _linkedin_title_match_score(
            candidate,
            match,
            company_name=company_name,
            bucket=bucket,
        )
        scored_matches.append((name_score, title_score, match))

    if not scored_matches:
        return None, None, "no_match"

    scored_matches.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            _normalize_identity(item[2].get("full_name")),
        )
    )
    best_score, best_title_score, best_match = scored_matches[0]
    if len(scored_matches) > 1:
        second_score, second_title_score, _ = scored_matches[1]
        if best_score == second_score:
            if best_title_score == second_title_score:
                return None, None, "ambiguous"
            if best_title_score < 4 and second_title_score >= best_title_score - 1:
                return None, None, "ambiguous"
        elif best_score < 100 and second_score >= best_score - 4 and second_title_score >= best_title_score:
            return None, None, "ambiguous"
    return best_match, best_score, "matched"


async def _enrich_existing_url_title(data: dict, *, company_name: str) -> None:
    """Recover a weak/missing title for a candidate that *already* has a
    LinkedIn URL, by reading that exact profile's public SERP snippet.

    The FIND search (``search_exact_linkedin_profile``) is name+company based
    and can mis-match, so it only runs for candidates with no URL. Here the
    candidate's own URL is matched exactly via ``public_profile_client`` — there
    is no wrong-person risk — so we can safely upgrade a weak title (e.g. a peer
    whose ``title`` is only the company name). Only fires when the existing
    title is actually weak/missing, so a candidate with a good title costs no
    extra search. Mutates ``data`` in place; fail-soft when nothing is found.
    """
    linkedin_url = data.get("linkedin_url")
    if not linkedin_url:
        return
    current_title = data.get("title")
    if not (
        data.get("_weak_title")
        or not current_title
        or _title_is_weak(current_title, company_name)
    ):
        return
    profile = await public_profile_client.enrich_profile(linkedin_url)
    if not profile:
        return
    recovered_title = profile.get("title") or ""
    if not recovered_title or _title_is_weak(recovered_title, company_name):
        return
    data["title"] = recovered_title
    data["_weak_title"] = False
    profile_data = _title_recovery_metadata(data, source="public_web")
    profile_data["linkedin_backfill_status"] = "title_enriched_exact_url"
    profile_data["linkedin_backfill_source"] = "public_web"
    data["profile_data"] = profile_data


async def _backfill_linkedin_profiles(
    candidates: list[dict],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None,
    bucket: str,
    context: JobContext | None = None,
    geo_terms: list[str] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    indexed_candidates = list(enumerate(candidates))

    def _priority(item: tuple[int, dict]) -> tuple[int, int, str]:
        _, candidate = item
        source = str(candidate.get("source") or "")
        trusted_public = _trusted_public_match(candidate, company_name, public_identity_slugs)
        geo_rank = _location_match_rank(candidate, context=context)
        missing_linkedin = not bool(candidate.get("linkedin_url"))
        public_boost = source in PUBLIC_WEB_SOURCES or bool(_public_profile_url(candidate))
        return (
            0 if missing_linkedin and trusted_public and geo_rank == 0 and public_boost else 1,
            0 if geo_rank == 0 else 1,
            _normalize_identity(candidate.get("full_name")),
        )

    async def _backfill_one(index: int, raw: dict) -> tuple[int, dict]:
        data = dict(raw)
        if data.get("linkedin_url"):
            # Already have the URL, so the name+company FIND search is moot — but
            # a weak title can still be upgraded by reading that exact profile.
            await _enrich_existing_url_title(data, company_name=company_name)
            return index, data

        public_url = _public_profile_url(data)
        if not public_url:
            return index, data

        employment_status = data.get("_employment_status") or _classify_employment_status(
            data,
            company_name,
            public_identity_slugs,
        )
        trusted_public = _trusted_public_match(data, company_name, public_identity_slugs)
        if employment_status != "current" and not trusted_public:
            data["profile_data"] = _linkedin_backfill_metadata(data, status="skipped")
            return index, data

        backfill_strategy = "exact_query"
        exact_title_hints = _linkedin_backfill_search_titles(
            data,
            bucket=bucket,
            company_name=company_name,
        )
        exact_name_variants = (
            _linkedin_backfill_name_variants(data.get("full_name"))
            if bucket in {"recruiters", "hiring_managers"}
            else []
        )
        exact_team_keywords = _linkedin_backfill_team_keywords(
            data,
            bucket=bucket,
        )
        exact_geo_terms = geo_terms if _location_match_rank(data, context=context) == 0 else None
        matches = await search_router_client.search_exact_linkedin_profile(
            data.get("full_name", ""),
            company_name,
            name_variants=exact_name_variants,
            title_hints=exact_title_hints,
            team_keywords=exact_team_keywords,
            geo_terms=exact_geo_terms,
            limit=5,
            search_profile=search_profile,
        )
        chosen, confidence, status = _choose_linkedin_backfill_match(
            data,
            matches,
            company_name=company_name,
            bucket=bucket,
        )
        if not chosen and bucket in {"recruiters", "hiring_managers"}:
            broad_titles = exact_title_hints
            if broad_titles:
                broader_matches = await search_router_client.search_people(
                    company_name,
                    titles=broad_titles,
                    team_keywords=None,
                    geo_terms=exact_geo_terms,
                    limit=8,
                    min_results=1,
                    search_profile=search_profile,
                )
                chosen, confidence, broad_status = _choose_linkedin_backfill_match(
                    data,
                    broader_matches,
                    company_name=company_name,
                    bucket=bucket,
                )
                if chosen:
                    matches = broader_matches
                    status = broad_status
                    backfill_strategy = "broad_company_title_query"
        data["profile_data"] = _linkedin_backfill_metadata(
            data,
            status=status,
            confidence=confidence,
            source=chosen.get("source", "search_router") if chosen else "search_router",
            strategy=backfill_strategy,
        )
        if chosen:
            data["linkedin_url"] = chosen.get("linkedin_url", "")
            recovered_title = chosen.get("title", "")
            if recovered_title and (
                bucket != "peers"
                or data.get("_weak_title")
                or _title_is_weak(data.get("title"), company_name)
            ):
                if not _title_is_weak(recovered_title, company_name):
                    data["title"] = recovered_title
                    data["_weak_title"] = False
                    profile_data = _title_recovery_metadata(
                        data,
                        source="linkedin_backfill",
                        confidence=confidence,
                    )
                    profile_data.update(data.get("profile_data") or {})
                    data["profile_data"] = profile_data
        return index, data

    if not indexed_candidates:
        return []

    semaphore = asyncio.Semaphore(3)

    async def _run_backfill(index: int, raw: dict) -> tuple[int, dict]:
        async with semaphore:
            return await _backfill_one(index, raw)

    prioritized = sorted(indexed_candidates, key=_priority)
    processed = await asyncio.gather(*(_run_backfill(index, raw) for index, raw in prioritized))
    processed.sort(key=lambda item: item[0])
    return [item for _, item in processed]


def _mark_linkedin_backfill_deferred(candidates: list[dict]) -> list[dict]:
    deferred: list[dict] = []
    for raw in candidates:
        candidate = dict(raw)
        profile_data = dict(candidate.get("profile_data") or {})
        if not candidate.get("linkedin_url"):
            profile_data.setdefault("linkedin_backfill_status", "deferred_interactive")
            profile_data.setdefault("linkedin_backfill_strategy", "deferred_after_response")
        candidate["profile_data"] = profile_data
        deferred.append(candidate)
    return deferred


async def _backfill_top_candidates(
    candidates: list[dict],
    *,
    top_n: int,
    company_name: str,
    public_identity_slugs: list[str] | None,
    bucket: str,
    context: JobContext | None = None,
    geo_terms: list[str] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    if not candidates or top_n <= 0:
        return candidates
    head = await _backfill_linkedin_profiles(
        candidates[:top_n],
        company_name=company_name,
        public_identity_slugs=public_identity_slugs,
        bucket=bucket,
        context=context,
        geo_terms=geo_terms,
        search_profile=search_profile,
    )
    return head + candidates[top_n:]
