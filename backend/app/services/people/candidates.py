"""Candidate search, dedupe, limits, and recovery gates for people discovery."""

import logging
import re
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import apollo_client, search_router_client
from app.utils.company_identity import (
    is_ambiguous_company_name,
)
from app.utils.job_context import (
    JobContext,
)

from app.services.people.classify import _classify_org_level, _classify_person
from app.services.people.occupation_gate import occupation_conflict
from app.services.people.company_match import PUBLIC_WEB_SOURCES, _candidate_matches_company, _classify_employment_status, _trusted_public_peer_match
from app.services.people.context import _candidate_geo_signal_match, _location_match_rank, _candidate_location_value
from app.services.people.identity import _normalize_identity
from app.services.people.ranking import _candidate_bucket_assignment_rank, _candidate_sort_key, _compute_usefulness_score
from app.services.people.titles import _allow_director_plus, _broaden_peer_titles_for_retry, _generic_manager_title, _is_manager_like, _is_recruiter_like, _is_senior_ic_fallback, _manager_candidate_has_engineering_context, _role_like_title, _title_is_weak
logger = logging.getLogger(__name__)


def _debug_candidate_summary(data: dict) -> dict[str, Any]:
    profile_data = data.get("profile_data") if isinstance(data.get("profile_data"), dict) else {}
    return {
        "full_name": data.get("full_name"),
        "title": data.get("title"),
        "source": data.get("source"),
        "linkedin_url": data.get("linkedin_url"),
        "location": _candidate_location_value(data),
        "employment_status": data.get("_employment_status"),
        "org_level": data.get("_org_level"),
        "search_provider": profile_data.get("search_provider"),
        "search_query": profile_data.get("search_query"),
        "search_query_index": profile_data.get("search_query_index"),
        "search_geo_terms": profile_data.get("search_geo_terms"),
    }
T = TypeVar("T")


DEFAULT_TARGET_COUNT_PER_BUCKET = 3


MAX_TARGET_COUNT_PER_BUCKET = 10


def _clamp_target_count_per_bucket(value: int | None) -> int:
    if value is None:
        return DEFAULT_TARGET_COUNT_PER_BUCKET
    return max(1, min(int(value), MAX_TARGET_COUNT_PER_BUCKET))


def _search_limit_for_target(target_count_per_bucket: int) -> int:
    return min(50, max(15, target_count_per_bucket * 5))


def _prepare_limit_for_target(target_count_per_bucket: int) -> int:
    return min(40, max(10, target_count_per_bucket * 4))


def _minimum_results_for_target(target_count_per_bucket: int) -> int:
    return max(1, min(target_count_per_bucket, 5))


def _count_linkedin_candidates(candidates: list[dict]) -> int:
    return sum(1 for candidate in candidates if candidate.get("linkedin_url"))


def _needs_more_bucket_candidates(candidates: list[dict], *, target_count_per_bucket: int) -> bool:
    return (
        len(candidates) < target_count_per_bucket
        or _count_linkedin_candidates(candidates) < min(target_count_per_bucket, len(candidates))
    )


def _needs_more_bucket_size_only(candidates: list[dict], *, target_count_per_bucket: int) -> bool:
    return len(candidates) < target_count_per_bucket


def _candidate_key(data: dict) -> str:
    linkedin_url = data.get("linkedin_url") or ""
    apollo_id = data.get("apollo_id") or ""
    full_name = _normalize_identity(data.get("full_name"))
    title = _normalize_identity(data.get("title"))
    if linkedin_url:
        return f"linkedin:{linkedin_url}"
    if apollo_id:
        return f"apollo:{apollo_id}"
    return f"name:{full_name}|title:{title}"


def _has_recruiter_lead_candidate(candidates: list[dict]) -> bool:
    for candidate in candidates:
        # Seniority/role signals come from title + snippet only. Including the
        # location let a candidate's city (e.g. "Canada") match a lead keyword
        # (audit M9), and "canada" was itself a region bias (audit H1).
        haystack = " ".join(
            part for part in [candidate.get("title", ""), candidate.get("snippet", "")]
            if part
        ).lower()
        if not _is_recruiter_like(haystack):
            continue
        if any(keyword in haystack for keyword in ("lead", "head", "manager", "director", "university recruitment")):
            return True
    return False


def _should_run_recruiter_targeted_recovery(
    candidates: list[dict],
    *,
    context: JobContext | None,
    target_count_per_bucket: int,
) -> bool:
    return (
        _needs_more_bucket_size_only(candidates, target_count_per_bucket=target_count_per_bucket)
        or not _has_local_geo_match(candidates, context=context)
        or not _has_recruiter_lead_candidate(candidates)
    )


def _should_run_peer_targeted_recovery(
    candidates: list[dict],
    *,
    context: JobContext | None,
    target_count_per_bucket: int,
) -> bool:
    return _needs_more_bucket_size_only(
        candidates,
        target_count_per_bucket=target_count_per_bucket,
    ) or not _has_local_geo_match(candidates, context=context)


async def _expand_peer_candidates(
    company_name: str,
    existing_candidates: list[dict],
    *,
    context: JobContext | None,
    public_identity_terms: list[str] | None,
    geo_terms: list[str] | None = None,
    company_domain: str | None = None,
    limit: int,
    min_results: int,
    debug_bucket: dict[str, Any] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    if not context:
        return existing_candidates
    if len(existing_candidates) >= min_results:
        return existing_candidates

    retry_titles = _broaden_peer_titles_for_retry(context)
    if not retry_titles:
        return existing_candidates

    retry_candidates = await _search_candidates(
        company_name,
        titles=retry_titles,
        departments=context.apollo_departments,
        team_keywords=None,
        geo_terms=geo_terms,
        public_identity_terms=public_identity_terms,
        company_domain=company_domain,
        limit=limit,
        min_results=max(1, min_results),
        debug_bucket=debug_bucket,
        search_profile=search_profile,
    )
    return _dedupe_candidates(existing_candidates, retry_candidates)


def _prepare_candidates(
    candidates: list[dict],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
    bucket: str,
    context: JobContext | None,
    limit: int,
    debug_funnel: dict[str, Any] | None = None,
) -> list[dict]:
    expected_type = {
        "recruiters": "recruiter",
        "hiring_managers": "hiring_manager",
        "peers": "peer",
    }[bucket]

    current_primary: list[dict] = []
    ambiguous_primary: list[dict] = []
    current_fallback: list[dict] = []
    ambiguous_fallback: list[dict] = []
    decisions: list[dict[str, Any]] = []

    for raw in candidates:
        data = dict(raw)
        decision = _debug_candidate_summary(data)
        title = data.get("title", "") or ""
        snippet = data.get("snippet", "") or ""
        if data.get("_posting_contact") or data.get("_hiring_team_capture") or data.get("_github_team_member"):
            # Pre-validated contacts bypass every heuristic gate (company match,
            # title/role, occupation): they are company-verified by construction
            # - named in this company's posting, on LinkedIn's hiring-team panel
            # for this req, or a confirmed contributor to this org's repos.
            decision["status"] = "kept"
            decision["reason"] = (
                "named_in_posting" if data.get("_posting_contact")
                else "hiring_team_capture" if data.get("_hiring_team_capture")
                else "github_team_member"
            )
            decisions.append(decision)
            if not data.get("_employment_status"):
                data["_employment_status"] = "current"
            current_primary.append(data)
            continue
        weak_title = data.get("_weak_title")
        if weak_title is None:
            weak_title = _title_is_weak(title, company_name)
            data["_weak_title"] = weak_title
        if bucket in {"recruiters", "hiring_managers"} and weak_title:
            # For ambiguous companies, weak titles from broad search may still
            # be real employees — include as low-priority fallbacks in peers bucket
            # instead of silently dropping them
            decision["status"] = "excluded"
            decision["reason"] = "weak_title"
            decisions.append(decision)
            continue
        if not _candidate_matches_company(data, company_name, public_identity_slugs):
            decision["status"] = "excluded"
            decision["reason"] = "company_mismatch"
            decisions.append(decision)
            continue
        if (
            bucket == "peers"
            and data.get("source") in PUBLIC_WEB_SOURCES
            and not _trusted_public_peer_match(
                data,
                company_name=company_name,
                public_identity_slugs=public_identity_slugs,
                context=context,
            )
        ):
            decision["status"] = "excluded"
            decision["reason"] = "untrusted_public_peer_candidate"
            decisions.append(decision)
            continue

        person_type = _classify_person(
            title,
            source=data.get("source", ""),
            snippet=snippet,
        )
        senior_ic_fallback = False
        if person_type != expected_type:
            if bucket == "hiring_managers" and person_type == "peer" and _is_senior_ic_fallback(title):
                senior_ic_fallback = True
            else:
                decision["status"] = "excluded"
                decision["reason"] = f"bucket_type_mismatch:{person_type}"
                decisions.append(decision)
                continue
        if bucket == "recruiters":
            if not (
                _is_recruiter_like(title)
                or _is_recruiter_like(snippet)
            ):
                decision["status"] = "excluded"
                decision["reason"] = "not_recruiter_like"
                decisions.append(decision)
                continue
            if title and not (
                _is_recruiter_like(title)
                or _role_like_title(title)
            ):
                decision["status"] = "excluded"
                decision["reason"] = "recruiter_title_not_role_like"
                decisions.append(decision)
                continue
        # Occupation gate: drop candidates whose function clearly differs from
        # the job's (e.g. an Engineering Manager surfaced for a sales req). Only
        # fires when both the job and the candidate function are confidently
        # known and different - ambiguous titles and posting-confirmed contacts
        # pass through. Recruiters are cross-functional, so their bucket is not
        # gated here.
        if (
            bucket in ("hiring_managers", "peers")
            and not data.get("_hiring_team_capture")
            and not data.get("_github_team_member")
            and context is not None
            and occupation_conflict(
                getattr(context, "occupation_keys", None),
                getattr(context, "department", None),
                title,
            )
        ):
            decision["status"] = "excluded"
            decision["reason"] = "occupation_conflict"
            decisions.append(decision)
            continue
        if bucket == "hiring_managers" and title and not (
            _is_manager_like(title)
            or _role_like_title(title)
        ):
            decision["status"] = "excluded"
            decision["reason"] = "not_manager_like"
            decisions.append(decision)
            continue
        if bucket == "hiring_managers" and _generic_manager_title(title) and not _manager_candidate_has_engineering_context(
            data,
            context=context,
        ):
            decision["status"] = "excluded"
            decision["reason"] = "generic_manager_without_engineering_context"
            decisions.append(decision)
            continue

        employment_status = _classify_employment_status(data, company_name, public_identity_slugs)
        if employment_status == "former":
            decision["status"] = "excluded"
            decision["reason"] = "former_employee"
            decisions.append(decision)
            continue

        org_level = _classify_org_level(
            data.get("title", ""),
            source=data.get("source", ""),
            snippet=data.get("snippet", ""),
        )

        if bucket == "hiring_managers" and org_level == "ic" and not senior_ic_fallback:
            decision["status"] = "excluded"
            decision["reason"] = "ic_manager_bucket_excluded"
            decisions.append(decision)
            continue
        if bucket == "peers" and org_level == "director_plus":
            decision["status"] = "excluded"
            decision["reason"] = "director_plus_peer_excluded"
            decisions.append(decision)
            continue

        is_fallback = False
        # Company-published leaders (own website) and press-quoted execs are the
        # leaders we want for non-engineering roles - being a director is not a
        # demotion for them, so they stay primary (still subject to the
        # occupation gate + company match above).
        published_leader = data.get("_company_site_leader") or data.get("_news_quote")
        if (
            bucket == "hiring_managers"
            and org_level == "director_plus"
            and not _allow_director_plus(context)
            and _location_match_rank(data, context=context) != 0
            and not published_leader
        ):
            is_fallback = True
        if bucket == "recruiters" and org_level == "director_plus" and _location_match_rank(data, context=context) != 0:
            is_fallback = True
        if senior_ic_fallback:
            is_fallback = True

        data["_employment_status"] = employment_status
        data["_org_level"] = org_level
        data["_director_fallback"] = is_fallback
        data["_senior_ic_fallback"] = senior_ic_fallback

        group_name = "current_primary"
        if employment_status == "current":
            if is_fallback:
                group_name = "current_fallback"
                current_fallback.append(data)
            else:
                current_primary.append(data)
        else:
            if is_fallback:
                group_name = "ambiguous_fallback"
                ambiguous_fallback.append(data)
            else:
                group_name = "ambiguous_primary"
                ambiguous_primary.append(data)
        data["_debug_group"] = group_name
        decision["status"] = "included"
        decision["group"] = group_name
        decision["employment_status"] = employment_status
        decision["org_level"] = org_level
        decisions.append(decision)

    current_primary.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))
    ambiguous_primary.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))
    current_fallback.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))
    ambiguous_fallback.sort(key=lambda item: _candidate_sort_key(item, bucket=bucket, context=context))

    ranked: list[dict] = []
    ranked.extend(current_primary)
    if len(ranked) < limit:
        ranked.extend(ambiguous_primary[: max(0, limit - len(ranked))])
    if len(ranked) < limit:
        ranked.extend(current_fallback[: max(0, limit - len(ranked))])
    if len(ranked) < limit:
        ranked.extend(ambiguous_fallback[: max(0, limit - len(ranked))])
    if debug_funnel is not None:
        debug_funnel["decisions"] = decisions
        debug_funnel["counts"] = {
            "input": len(candidates),
            "current_primary": len(current_primary),
            "ambiguous_primary": len(ambiguous_primary),
            "current_fallback": len(current_fallback),
            "ambiguous_fallback": len(ambiguous_fallback),
            "ranked": len(ranked),
        }
        debug_funnel["ranked"] = [
            {
                **_debug_candidate_summary(item),
                "group": item.get("_debug_group"),
                "sort_key": list(_candidate_sort_key(item, bucket=bucket, context=context)),
                "usefulness_score": _compute_usefulness_score(
                    item,
                    bucket=bucket,
                    context=context,
                    company_name=company_name,
                    public_identity_slugs=public_identity_slugs,
                ),
            }
            for item in ranked[: min(len(ranked), max(limit, 15))]
        ]
    return ranked[:limit]


def _should_expand_with_theorg(
    company_name: str,
    current_counts: dict[str, int],
    *,
    context: JobContext | None = None,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
) -> bool:
    target_count_per_bucket = _clamp_target_count_per_bucket(target_count_per_bucket)
    if is_ambiguous_company_name(company_name):
        return True
    if any(count < target_count_per_bucket for count in current_counts.values()):
        return True
    # Hiring managers are the hardest bucket to get right from titles alone.
    # When the job context carries team keywords, The Org's team pages can
    # cross-check who actually leads that team, so expand unless the bucket
    # is already overflowing.
    if (
        context is not None
        and getattr(context, "team_keywords", None)
        and current_counts.get("hiring_managers", 0) < target_count_per_bucket + 2
    ):
        return True
    # Non-engineering roles: public-web x-ray surfaces engineers, not the right
    # function, so always consult The Org's authoritative org chart for the
    # leadership roster + reporting-line managers.
    if context is not None and getattr(context, "occupation_keys", None):
        from app.services.occupation_taxonomy import is_engineering_flavored
        if not is_engineering_flavored(context.occupation_keys, department=getattr(context, "department", None)):
            return True
    return False


def _dedupe_candidate_bucket_groups(
    bucket_groups: dict[str, list[dict]],
    *,
    context: JobContext | None,
    company_name: str = "",
    public_identity_slugs: list[str] | None = None,
) -> dict[str, list[dict]]:
    winners: dict[str, tuple[str, tuple[int, int, int, int, int, int, str]]] = {}
    for bucket, candidates in bucket_groups.items():
        for candidate in candidates:
            key = _candidate_key(candidate)
            rank = _candidate_bucket_assignment_rank(
                bucket,
                candidate,
                context=context,
                company_name=company_name,
                public_identity_slugs=public_identity_slugs,
            )
            current = winners.get(key)
            if current is None or rank < current[1]:
                winners[key] = (bucket, rank)

    return {
        bucket: [
            candidate
            for candidate in candidates
            if winners.get(_candidate_key(candidate), (None, None))[0] == bucket
        ]
        for bucket, candidates in bucket_groups.items()
    }


def _dedupe_candidates(*groups: list[dict]) -> list[dict]:
    """Dedupe candidates, recording cross-source corroboration on the survivor.

    When the same person is surfaced by more than one discovery strategy the
    duplicate is collapsed into the first occurrence, but the distinct ``source``
    values are unioned onto ``_corroborated_by``. Agreement across independent
    strategies is a strong accuracy signal that ranking rewards
    (`ranking._corroboration_rank`); previously the duplicate was simply dropped
    and the signal lost.
    """
    deduped: list[dict] = []
    kept_by_key: dict[str, dict] = {}
    for group in groups:
        for candidate in group:
            key = _candidate_key(candidate)
            source = candidate.get("source")
            existing = kept_by_key.get(key)
            if existing is not None:
                if source:
                    corroborated = existing.setdefault("_corroborated_by", [])
                    if source not in corroborated:
                        corroborated.append(source)
                continue
            kept_by_key[key] = candidate
            candidate["_corroborated_by"] = [source] if source else []
            deduped.append(candidate)
    # Mirror ≥2-source corroboration into profile_data so it persists on the
    # Person row and serializes to the UI (the landing page promises the user
    # can SEE when multiple independent sources agree, not just rank by it).
    for candidate in deduped:
        sources = candidate.get("_corroborated_by") or []
        if len(sources) >= 2:
            profile_data = candidate.get("profile_data")
            if not isinstance(profile_data, dict):
                profile_data = {}
                candidate["profile_data"] = profile_data
            profile_data["corroborated_by"] = list(sources)
    return deduped


def _balanced_candidate_mix(*groups: list[dict], limit: int) -> list[dict]:
    mixed: list[dict] = []
    seen: set[str] = set()
    # Per-group cursors so a duplicate in one group doesn't waste another group's
    # round-robin slot. Previously a single shared index advanced for every group
    # whenever any candidate was skipped, starving groups with early dupes (M8).
    pointers = [0] * len(groups)
    active = True
    while active and len(mixed) < limit:
        active = False
        for group_index, group in enumerate(groups):
            # Consume exactly one fresh (not-yet-seen) candidate from this group,
            # advancing past any duplicates encountered along the way.
            while pointers[group_index] < len(group):
                candidate = group[pointers[group_index]]
                pointers[group_index] += 1
                key = _candidate_key(candidate)
                if key in seen:
                    continue
                seen.add(key)
                mixed.append(candidate)
                active = True
                break
            if len(mixed) >= limit:
                break
    return mixed


def _interactive_enrichment_limit_for_target(target_count_per_bucket: int) -> int:
    return max(4, target_count_per_bucket + 1)


def _limit_interactive_bucket(items: list[T], *, target_count_per_bucket: int) -> list[T]:
    return items[:_interactive_enrichment_limit_for_target(target_count_per_bucket)]


def _has_local_geo_match(candidates: list[dict], *, context: JobContext | None) -> bool:
    return any(_candidate_geo_signal_match(candidate, context=context) for candidate in candidates)


def _should_run_manager_geo_recovery(
    candidates: list[dict],
    *,
    context: JobContext | None,
    target_count_per_bucket: int,
) -> bool:
    return _needs_more_bucket_size_only(
        candidates,
        target_count_per_bucket=target_count_per_bucket,
    ) or not _has_local_geo_match(candidates, context=context)


def _cached_title_matches(candidate_title: str | None, requested_titles: list[str]) -> bool:
    """True when a cached candidate's title is relevant to the requested bucket.

    The known-people cache is company-wide, so without this check a handful of
    cached rows from one bucket (e.g. recruiters) would short-circuit the live
    search for a different bucket (e.g. hiring managers) and leave it empty.
    A requested title matches when all of its significant tokens appear in the
    candidate title. An empty request list means any title qualifies.
    """
    if not requested_titles:
        return True
    if not candidate_title:
        return False
    haystack = candidate_title.casefold()
    for requested in requested_titles:
        tokens = [tok for tok in re.split(r"[^a-z0-9]+", requested.casefold()) if len(tok) > 2]
        if tokens and all(tok in haystack for tok in tokens):
            return True
    return False


async def _search_candidates(
    company_name: str,
    *,
    titles: list[str],
    departments: list[str] | None = None,
    seniority: list[str] | None = None,
    team_keywords: list[str] | None = None,
    geo_terms: list[str] | None = None,
    public_identity_terms: list[str] | None = None,
    company_domain: str | None = None,
    limit: int = 5,
    min_results: int = 2,
    db: AsyncSession | None = None,
    debug_bucket: dict[str, Any] | None = None,
    search_profile: str = "standard",
) -> list[dict]:
    """Run Apollo plus routed SERP/public search with dedupe.

    When *db* is provided, checks the global known-people cache first.
    If the cache has enough results, external API calls are skipped.
    """
    # --- Global cache lookup (when db available) ---
    cached_results: list[dict] = []
    if debug_bucket is not None:
        debug_bucket["search_inputs"] = {
            "company_name": company_name,
            "titles": titles,
            "departments": departments,
            "seniority": seniority,
            "team_keywords": team_keywords,
            "geo_terms": geo_terms,
            "public_identity_terms": public_identity_terms,
            "company_domain": company_domain,
            "limit": limit,
            "min_results": min_results,
        }
    if db is not None:
        try:
            from app.services.known_people_service import lookup_known_people
            cached_results = await lookup_known_people(
                db, company_name=company_name, limit=limit,
            )
        except Exception:
            # Warning, not debug: a persistent failure here (Redis down, schema
            # drift, SQLAlchemy error) should be visible, not silently swallowed
            # while the feature appears to "work" with empty cache (audit M12).
            logger.warning("Known people cache lookup failed for %s", company_name, exc_info=True)
            cached_results = []

        relevant_cached = [
            item for item in cached_results
            if _cached_title_matches(item.get("title"), titles)
        ]
        if debug_bucket is not None:
            debug_bucket["known_people"] = {
                "count": len(cached_results),
                "relevant_count": len(relevant_cached),
                "cache_hit": len(relevant_cached) >= min_results,
                "sample_results": [_debug_candidate_summary(item) for item in relevant_cached[:5]],
            }
        if len(relevant_cached) >= min_results:
            return relevant_cached[: max(limit, 8)]

    apollo_filtered = await apollo_client.search_people(
        company_name,
        titles=titles,
        departments=departments,
        seniority=seniority,
        limit=limit,
    )
    apollo_unfiltered: list[dict] = []
    if len(apollo_filtered) < min_results and departments:
        apollo_unfiltered = await apollo_client.search_people(
            company_name,
            titles=titles,
            seniority=seniority,
            limit=limit,
        )
    if debug_bucket is not None:
        debug_bucket["apollo"] = {
            "filtered_count": len(apollo_filtered),
            "unfiltered_count": len(apollo_unfiltered),
            "filtered_results": [_debug_candidate_summary(item) for item in apollo_filtered[:5]],
            "unfiltered_results": [_debug_candidate_summary(item) for item in apollo_unfiltered[:5]],
        }

    brave_results = []
    merged = _dedupe_candidates(apollo_filtered, apollo_unfiltered)
    linkedin_provider_traces: list[dict[str, Any]] | None = [] if debug_bucket is not None else None
    if len(merged) < min_results:
        brave_results = await search_router_client.search_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            geo_terms=geo_terms,
            limit=max(limit, 5),
            min_results=min_results,
            company_domain=company_domain,
            debug_traces=linkedin_provider_traces,
            search_profile=search_profile,
        )

    public_results = []
    merged = _dedupe_candidates(merged, brave_results)
    public_provider_traces: list[dict[str, Any]] | None = [] if debug_bucket is not None else None
    if len(merged) < min_results or is_ambiguous_company_name(company_name) or bool(public_identity_terms):
        public_results = await search_router_client.search_public_people(
            company_name,
            titles=titles,
            team_keywords=team_keywords,
            public_identity_terms=public_identity_terms,
            geo_terms=geo_terms,
            limit=max(limit, 5),
            min_results=min_results,
            debug_traces=public_provider_traces,
            search_profile=search_profile,
        )

    target_limit = max(limit, 8)
    seed_results = _dedupe_candidates(cached_results, apollo_filtered, apollo_unfiltered)
    mixed_external = _balanced_candidate_mix(
        public_results,
        brave_results,
        limit=max(0, target_limit - len(seed_results)),
    )
    deduped = _dedupe_candidates(seed_results, mixed_external)
    if debug_bucket is not None:
        debug_bucket["linkedin_provider_traces"] = linkedin_provider_traces or []
        debug_bucket["public_provider_traces"] = public_provider_traces or []
        debug_bucket["returned_candidates"] = [_debug_candidate_summary(item) for item in deduped[:10]]
    return deduped[:target_limit]
