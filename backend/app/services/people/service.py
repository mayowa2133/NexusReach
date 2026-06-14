"""Top-level people discovery orchestrators."""

import asyncio
import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import github_client, proxycurl_client, search_router_client, tavily_search_client
from app.models.job import Job
from app.models.profile import Profile
from app.models.person import Person
from app.services import linkedin_graph_service
from app.services.employment_verification_service import verify_people_current_company
from app.services.theorg_discovery_service import discover_theorg_candidates
from app.utils.company_identity import (
    effective_public_identity_slugs,
    is_ambiguous_company_name,
    normalize_company_name,
)
from app.utils.job_context import (
    JobContext,
    build_job_geo_terms,
    extract_job_context,
    normalize_job_locations,
)
from app.services.occupation_taxonomy import (
    is_engineering_flavored as _occupation_is_engineering_flavored,
)

from app.services.people.buckets import _append_bucket, _backfill_sparse_hiring_manager_bucket, _bucketed_linkedin_slugs, _finalize_bucketed
from app.services.people.candidates import DEFAULT_TARGET_COUNT_PER_BUCKET, _clamp_target_count_per_bucket, _debug_candidate_summary, _dedupe_candidate_bucket_groups, _dedupe_candidates, _expand_peer_candidates, _has_recruiter_lead_candidate, _interactive_enrichment_limit_for_target, _limit_interactive_bucket, _minimum_results_for_target, _needs_more_bucket_candidates, _needs_more_bucket_size_only, _prepare_candidates, _prepare_limit_for_target, _search_candidates, _search_limit_for_target, _should_expand_with_theorg, _should_run_manager_geo_recovery, _should_run_peer_targeted_recovery, _should_run_recruiter_targeted_recovery
from app.services.people.classify import _classify_org_level, _classify_person, _classify_person_with_confidence
from app.services.people.affinity import annotate_affinity
from app.services.people.company_site import discover_company_site_leaders, discover_company_site_recruiters
from app.services.people.public_footprint import discover_public_footprint_leaders
from app.services.people.github_team import resolve_github_org, resolve_team_contacts
from app.services.people.outcome_priors import load_reply_priors, stamp_outcome_priors
from app.services.people.title_llm import normalize_title_key, resolve_ambiguous_titles
from app.services.people.company_match import _candidate_matches_company, _classify_employment_status
from app.services.people.context import _bucket_geo_terms, _build_roles_context
from app.services.people.linkedin_backfill import _backfill_linkedin_profiles, _mark_linkedin_backfill_deferred
from app.services.people.persistence import _store_person, get_or_create_company
from app.services.people.ranking import _score_contextual_candidates_fast
from app.services.people.theorg_recovery import _candidate_theorg_slug_candidates, _merge_company_public_identity_slugs, _recover_candidate_titles, _saved_theorg_slug_candidates
from app.services.people.titles import _companywide_manager_titles, _companywide_peer_titles, _companywide_recruiter_titles, _initial_manager_titles, _is_manager_like, _is_recruiter_like, _is_senior_ic_fallback, _manager_geo_recovery_keywords, _manager_geo_recovery_titles, _manager_seniority_filters, _peer_seniority_filters, _peer_targeted_recovery_keywords, _peer_targeted_recovery_titles, _prioritize_titles_for_search, _recruiter_targeted_recovery_keywords, _recruiter_targeted_recovery_titles, _sanitize_search_keywords
logger = logging.getLogger(__name__)


def _debug_person_summary(person: Person) -> dict[str, Any]:
    profile_data = person.profile_data if isinstance(person.profile_data, dict) else {}
    return {
        "id": str(person.id) if person.id else None,
        "full_name": person.full_name,
        "title": person.title,
        "person_type": person.person_type,
        "linkedin_url": person.linkedin_url,
        "location": profile_data.get("location"),
        "usefulness_score": getattr(person, "usefulness_score", None),
        "match_quality": getattr(person, "match_quality", None),
        "match_reason": getattr(person, "match_reason", None),
        "company_match_confidence": getattr(person, "company_match_confidence", None),
        "employment_status": getattr(person, "employment_status", None),
        "org_level": getattr(person, "org_level", None),
        "search_query": profile_data.get("search_query"),
        "search_provider": profile_data.get("search_provider"),
    }


def _record_timing(
    debug: dict[str, Any] | None,
    *,
    stage: str,
    started_at: float,
    **details: Any,
) -> None:
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    logger.warning("people_search_timing stage=%s duration_ms=%.2f details=%s", stage, duration_ms, details)
    if debug is None:
        return
    timings = debug.setdefault("timings", [])
    timings.append(
        {
            "stage": stage,
            "duration_ms": duration_ms,
            **details,
        }
    )



def _posting_contact_candidates(job, context: JobContext | None) -> list[dict]:
    """Build top-priority candidates from contacts named in the posting itself.

    A person-specific contact email published in the job description is the
    designated contact for the req - stronger evidence than anything search
    can find. Generic inboxes (jobs@) are skipped: they are not people.
    """
    contacts = list(getattr(context, "posting_contacts", None) or [])
    candidates: list[dict] = []
    for contact in contacts:
        if contact.get("generic"):
            continue
        email = contact.get("email")
        name = contact.get("name")
        if not email:
            continue
        candidates.append(
            {
                "full_name": name or email.split("@", 1)[0].replace(".", " ").title(),
                "title": "Recruiter",
                "source": "job_posting",
                "snippet": f"Named as the contact in {job.company_name}'s own posting for {job.title}.",
                "email": email,
                "email_source": "job_posting",
                "_posting_contact": True,
                "profile_data": {
                    "company_match_confidence": "verified",
                    "posting_contact": True,
                    "posting_contact_email": email,
                },
            }
        )
    return candidates


async def _title_overrides_for(candidates: list[dict]) -> dict[str, str]:
    """Resolve LLM bucket overrides for candidates with ambiguous titles."""
    ambiguous = [
        c.get("title", "")
        for c in candidates
        if not _classify_person_with_confidence(
            c.get("title", ""),
            snippet=c.get("snippet", ""),
            source=c.get("source", ""),
        )[1]
    ]
    if not ambiguous:
        return {}
    return await resolve_ambiguous_titles(ambiguous)


def _bucket_with_tiebreak(
    candidate: dict, overrides: dict[str, str], *, use_snippet: bool = True
) -> str:
    """Keyword bucket with the LLM override applied to the ambiguous tail."""
    snippet = candidate.get("snippet", "") if use_snippet else ""
    source = candidate.get("source", "") if use_snippet else ""
    bucket, confident = _classify_person_with_confidence(
        candidate.get("title", ""), snippet=snippet, source=source
    )
    if confident:
        return bucket
    override = overrides.get(normalize_title_key(candidate.get("title")))
    if override in ("recruiter", "hiring_manager", "peer"):
        return override
    return bucket


async def _gather_nontech_leaders(
    company_name: str,
    domain: str | None,
    context: JobContext | None,
) -> dict[str, list[dict]]:
    """Non-technical leadership candidates from the three own-evidence sources.

    Returns ``{"site": [...], "news": [...], "footprint": [...]}`` so callers can
    record per-source debug. Empty for engineering-flavored contexts (GitHub
    covers those); bounded, cached, and fail-soft per source. Shared by both the
    job-aware and People-page company flows so non-tech recall is identical.
    """
    out: dict[str, list[dict]] = {"site": [], "news": [], "footprint": []}
    if _occupation_is_engineering_flavored(
        context.occupation_keys if context else None,
        department=context.department if context else None,
    ):
        return out
    title_hints = list(context.manager_titles[:3]) if context else []
    try:
        out["site"] = await discover_company_site_leaders(company_name, domain)
    except Exception:
        logger.debug("company-site leadership discovery failed; skipping", exc_info=True)
    try:
        out["news"] = await tavily_search_client.search_executive_quotes(company_name, title_hints)
    except Exception:
        logger.debug("news executive-quote mining failed; skipping", exc_info=True)
    try:
        out["footprint"] = await discover_public_footprint_leaders(company_name, title_hints)
    except Exception:
        logger.debug("public-footprint mining failed; skipping", exc_info=True)
    return out


async def _gather_company_site_recruiters(company_name: str, domain: str | None) -> list[dict]:
    """Recruiters from the company's own recruiting/careers-team page.

    Own-domain, free, and the best non-companion recruiter source. Runs for
    every role type (recruiters are universal); bounded, cached, fail-soft.
    Shared by both people flows so recruiter recall is identical.
    """
    if not domain:
        return []
    try:
        return await discover_company_site_recruiters(company_name, domain)
    except Exception:
        logger.debug("company-site recruiter discovery failed; skipping", exc_info=True)
        return []


async def search_people_at_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
    roles: list[str] | None = None,
    github_org: str | None = None,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
) -> dict:
    """Find people at a company using company-level search."""
    import time as _time

    from app.models.search_log import SearchLog

    _t0 = _time.monotonic()
    target_count_per_bucket = _clamp_target_count_per_bucket(target_count_per_bucket)
    search_limit = _search_limit_for_target(target_count_per_bucket)
    prepare_limit = _prepare_limit_for_target(target_count_per_bucket)
    minimum_results = _minimum_results_for_target(target_count_per_bucket)

    roles_context = _build_roles_context(roles)

    company = await get_or_create_company(db, user_id, company_name)
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    # Split user-provided roles into the correct buckets instead of dumping
    # all roles into every search.  Recruiter-like roles feed the recruiter
    # search, manager-like roles feed the manager search, and everything else
    # feeds the peer search.  Buckets always fall back to companywide defaults
    # so that we never search for "University Recruiter" in the manager bucket.
    recruiter_titles = _companywide_recruiter_titles(roles_context)
    manager_titles = _companywide_manager_titles(roles_context)
    peer_titles = _companywide_peer_titles(roles_context)
    if roles:
        extra_recruiter = [r for r in roles if _is_recruiter_like(r)]
        extra_manager = [r for r in roles if _is_manager_like(r) and not _is_recruiter_like(r)]
        extra_peer = [r for r in roles if not _is_recruiter_like(r) and not _is_manager_like(r)]
        if extra_recruiter:
            recruiter_titles = list(dict.fromkeys(extra_recruiter + recruiter_titles))
        if extra_manager:
            manager_titles = list(dict.fromkeys(extra_manager + manager_titles))
        if extra_peer:
            peer_titles = list(dict.fromkeys(extra_peer + peer_titles))

    # Run all three bucket searches concurrently for ~3x faster initial discovery
    recruiter_candidates, manager_candidates, peer_candidates = await asyncio.gather(
        _search_candidates(
            company_name,
            titles=recruiter_titles,
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
            db=db,
        ),
        _search_candidates(
            company_name,
            titles=manager_titles,
            seniority=["manager", "director", "vp"],
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
            db=db,
        ),
        _search_candidates(
            company_name,
            titles=peer_titles,
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
            db=db,
        ),
    )
    # For early-career searches, run additional queries with common intern/new-grad
    # phrasing since LinkedIn profiles use varied title formats (e.g. "SWE Intern",
    # "Software Engineer Intern", "Incoming SWE Intern") and a single query batch
    # often returns mostly former interns or posts rather than current profiles.
    if roles_context and roles_context.early_career:
        early_career_titles = [
            "SWE Intern",
            "Software Engineer",
            "Production Engineer",
            "New Grad",
        ]
        extra_peers = await _search_candidates(
            company_name,
            titles=early_career_titles,
            public_identity_terms=public_identity_terms,
            limit=search_limit,
            min_results=minimum_results,
        )
        peer_candidates = _dedupe_candidates(peer_candidates, extra_peers)
    saved_slug_candidates = await _saved_theorg_slug_candidates(
        db,
        user_id=user_id,
        company=company,
    )
    _merge_company_public_identity_slugs(
        company,
        company_name,
        _candidate_theorg_slug_candidates(
            recruiter_candidates,
            manager_candidates,
            peer_candidates,
            company_name=company_name,
            trusted_slugs=public_identity_terms,
        )
        + saved_slug_candidates,
    )
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    recruiter_candidates, manager_candidates, peer_candidates = await asyncio.gather(
        _recover_candidate_titles(recruiter_candidates, company=company, company_name=company_name),
        _recover_candidate_titles(manager_candidates, company=company, company_name=company_name),
        _recover_candidate_titles(peer_candidates, company=company, company_name=company_name),
    )

    # Non-technical leadership sources (company-website roster, news/PR exec
    # quotes, speaker/byline/X-bio footprint). The job-aware flow runs these for
    # non-engineering roles; the People-page company browse needs the same
    # recall so a non-tech seeker exploring a company isn't left with x-ray-only
    # results. Deduped into the manager bucket and gated by function downstream.
    nontech_leaders = await _gather_nontech_leaders(
        company_name,
        company.domain if getattr(company, "domain", None) else None,
        roles_context,
    )
    combined_leaders = nontech_leaders["site"] + nontech_leaders["news"] + nontech_leaders["footprint"]
    if combined_leaders:
        manager_candidates = _dedupe_candidates(manager_candidates, combined_leaders)

    # Recruiting/TA-team page (own-domain recruiters). Runs for all role types.
    site_recruiters = await _gather_company_site_recruiters(
        company_name, company.domain if getattr(company, "domain", None) else None
    )
    if site_recruiters:
        recruiter_candidates = _dedupe_candidates(recruiter_candidates, site_recruiters)

    # --- Write-through to global known people cache ---
    try:
        from app.services.known_people_service import write_candidates_to_cache
        all_candidates = recruiter_candidates + manager_candidates + peer_candidates
        await write_candidates_to_cache(
            db,
            all_candidates,
            company_name=company_name,
            company_domain=company.domain if hasattr(company, "domain") else None,
        )
    except Exception:
        logger.warning("Known people cache write-through failed for %s", company_name, exc_info=True)

    recruiter_results = _prepare_candidates(
        recruiter_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="recruiters",
        context=roles_context,
        limit=prepare_limit,
    )
    manager_results = _prepare_candidates(
        manager_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
        context=roles_context,
        limit=prepare_limit,
    )
    peer_results = _prepare_candidates(
        peer_candidates,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
        context=roles_context,
        limit=prepare_limit,
    )

    if _should_expand_with_theorg(
        company_name,
        {
            "recruiters": len(recruiter_results),
            "hiring_managers": len(manager_results),
            "peers": len(peer_results),
        },
        context=roles_context,
        target_count_per_bucket=target_count_per_bucket,
    ):
        theorg_candidates = await discover_theorg_candidates(
            company,
            company_name=company_name,
            context=roles_context,
            current_counts={
                "recruiters": len(recruiter_results),
                "hiring_managers": len(manager_results),
                "peers": len(peer_results),
            },
            slug_candidates=_candidate_theorg_slug_candidates(
                recruiter_candidates,
                manager_candidates,
                peer_candidates,
                company_name=company_name,
                trusted_slugs=public_identity_terms,
            )
            + saved_slug_candidates,
        )
        recruiter_results = _prepare_candidates(
            _dedupe_candidates(recruiter_candidates, theorg_candidates.get("recruiters", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=roles_context,
            limit=prepare_limit,
        )
        manager_results = _prepare_candidates(
            _dedupe_candidates(manager_candidates, theorg_candidates.get("hiring_managers", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=roles_context,
            limit=prepare_limit,
        )
        peer_results = _prepare_candidates(
            _dedupe_candidates(peer_candidates, theorg_candidates.get("peers", [])),
            company_name=company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=roles_context,
            limit=prepare_limit,
        )

    recruiter_results, manager_results, peer_results = await asyncio.gather(
        _backfill_linkedin_profiles(
            recruiter_results, company_name=company_name,
            public_identity_slugs=public_identity_terms, bucket="recruiters",
        ),
        _backfill_linkedin_profiles(
            manager_results, company_name=company_name,
            public_identity_slugs=public_identity_terms, bucket="hiring_managers",
        ),
        _backfill_linkedin_profiles(
            peer_results, company_name=company_name,
            public_identity_slugs=public_identity_terms, bucket="peers",
        ),
    )

    if any(
        _needs_more_bucket_candidates(results, target_count_per_bucket=target_count_per_bucket)
        for results in (recruiter_results, manager_results, peer_results)
    ):
        if _needs_more_bucket_candidates(recruiter_results, target_count_per_bucket=target_count_per_bucket):
            recruiter_candidates = _dedupe_candidates(
                recruiter_candidates,
                await _search_candidates(
                    company_name,
                    titles=_companywide_recruiter_titles(roles_context),
                    public_identity_terms=public_identity_terms,
                    limit=search_limit,
                    min_results=minimum_results,
                ),
            )
            recruiter_candidates = await _recover_candidate_titles(
                recruiter_candidates,
                company=company,
                company_name=company_name,
            )
            recruiter_results = _prepare_candidates(
                recruiter_candidates,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="recruiters",
                context=roles_context,
                limit=prepare_limit,
            )
            recruiter_results = await _backfill_linkedin_profiles(
                recruiter_results,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="recruiters",
            )

        if _needs_more_bucket_candidates(manager_results, target_count_per_bucket=target_count_per_bucket):
            manager_candidates = _dedupe_candidates(
                manager_candidates,
                await _search_candidates(
                    company_name,
                    titles=_companywide_manager_titles(roles_context),
                    seniority=["manager", "director", "vp"],
                    public_identity_terms=public_identity_terms,
                    limit=search_limit,
                    min_results=minimum_results,
                ),
            )
            manager_candidates = await _recover_candidate_titles(
                manager_candidates,
                company=company,
                company_name=company_name,
            )
            manager_results = _prepare_candidates(
                manager_candidates,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
                context=roles_context,
                limit=prepare_limit,
            )
            manager_results = await _backfill_linkedin_profiles(
                manager_results,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
            )

        if _needs_more_bucket_candidates(peer_results, target_count_per_bucket=target_count_per_bucket):
            peer_candidates = _dedupe_candidates(
                peer_candidates,
                await _search_candidates(
                    company_name,
                    titles=_companywide_peer_titles(roles_context, fallback_titles=peer_titles),
                    public_identity_terms=public_identity_terms,
                    limit=search_limit,
                    min_results=minimum_results,
                ),
            )
            peer_candidates = await _recover_candidate_titles(
                peer_candidates,
                company=company,
                company_name=company_name,
            )
            peer_results = _prepare_candidates(
                peer_candidates,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
                context=roles_context,
                limit=prepare_limit,
            )
            peer_results = await _backfill_linkedin_profiles(
                peer_results,
                company_name=company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
            )

    bucket_candidate_groups = _dedupe_candidate_bucket_groups(
        {
            "recruiters": recruiter_results,
            "hiring_managers": manager_results,
            "peers": peer_results,
        },
        context=roles_context,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
    )
    recruiter_results = bucket_candidate_groups["recruiters"]
    manager_results = bucket_candidate_groups["hiring_managers"]
    peer_results = bucket_candidate_groups["peers"]

    github_members: list[dict] = []
    # Only enrich with GitHub org membership when the job is engineering-flavored
    # (software, ML/AI, data engineering, cybersecurity, etc.). For non-engineering
    # roles like Sales, Marketing, or Healthcare the GitHub signal is noise.
    github_allowed = _occupation_is_engineering_flavored(
        roles_context.occupation_keys if roles_context else None,
        department=roles_context.department if roles_context else None,
    )
    if github_org and github_allowed:
        team_keywords_for_github = list(roles_context.team_keywords) if roles_context else []
        if team_keywords_for_github:
            github_members = await github_client.search_team_contributors(
                github_org,
                team_keywords_for_github,
                limit=max(5, target_count_per_bucket),
            )
        if not github_members:
            github_members = await github_client.search_org_members(
                github_org,
                limit=max(5, target_count_per_bucket),
            )
        for member in github_members:
            repos = await github_client.get_user_repos(member["login"], limit=3)
            languages = list({repo["language"] for repo in repos if repo.get("language")})
            member["github_data"] = {"repos": repos, "languages": languages}
            member["github_url"] = member.get("github_url", "")
    elif github_org and not github_allowed:
        logger.debug(
            "Skipping GitHub org enrichment for non-engineering job: org=%s occupations=%s",
            github_org,
            roles_context.occupation_keys if roles_context else None,
        )

    bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
    seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}

    for data in recruiter_results:
        person = await _store_person(db, user_id, company, data, "recruiter")
        _append_bucket(bucketed, seen, person, data, explicit_type="recruiter", context=roles_context, company_name=company_name, public_identity_slugs=public_identity_terms)

    manager_overrides = await _title_overrides_for(manager_results)
    for data in manager_results:
        person = await _store_person(
            db,
            user_id,
            company,
            data,
            _bucket_with_tiebreak(data, manager_overrides, use_snippet=False),
        )
        _append_bucket(bucketed, seen, person, data, context=roles_context, company_name=company_name, public_identity_slugs=public_identity_terms)

    for data in peer_results:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", context=roles_context, company_name=company_name, public_identity_slugs=public_identity_terms)

    for data in github_members:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", context=roles_context, company_name=company_name)

    await verify_people_current_company(
        bucketed,
        company_name=company_name,
        company_domain=company.domain if company.domain_trusted else None,
        company_public_identity_slugs=public_identity_terms,
    )
    _backfill_sparse_hiring_manager_bucket(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
    )
    your_connections = await linkedin_graph_service.get_connections_for_company(
        db,
        user_id,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
    )
    direct_connections = await linkedin_graph_service.get_connections_by_linkedin_slugs(
        db,
        user_id,
        _bucketed_linkedin_slugs(bucketed),
    )
    direct_follows = await linkedin_graph_service.get_followed_people_by_linkedin_slugs(
        db,
        user_id,
        _bucketed_linkedin_slugs(bucketed),
    )
    company_follows = await linkedin_graph_service.get_followed_companies_for_company(
        db,
        user_id,
        company_name=company_name,
        public_identity_slugs=public_identity_terms,
    )
    linkedin_graph_service.apply_warm_path_annotations(
        bucketed,
        company_name=company_name,
        your_connections=your_connections,
        direct_connections=direct_connections,
    )
    linkedin_graph_service.apply_follow_signal_annotations(
        bucketed,
        company_name=company_name,
        direct_follows=direct_follows,
        company_follows=company_follows,
    )
    finalized = _finalize_bucketed(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
        location_terms=getattr(roles_context, "job_geo_terms", None),
    )

    # Record search in audit log
    elapsed = _time.monotonic() - _t0
    search_log = SearchLog(
        user_id=user_id,
        company_id=company.id,
        company_name=company_name,
        search_type="company",
        recruiter_count=len(finalized["recruiters"]),
        manager_count=len(finalized["hiring_managers"]),
        peer_count=len(finalized["peers"]),
        duration_seconds=round(elapsed, 2),
    )
    db.add(search_log)
    await db.commit()

    return {
        "company": company,
        "your_connections": [
            linkedin_graph_service.serialize_connection(connection)
            for connection in your_connections
        ],
        **finalized,
    }


async def search_people_for_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    search_depth: str = "deep",
    min_relevance_score: int = 1,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
    include_debug: bool = False,
) -> dict:
    """Find people at a company using extracted job context."""
    total_started_at = time.monotonic()
    target_count_per_bucket = _clamp_target_count_per_bucket(target_count_per_bucket)
    search_limit = _search_limit_for_target(target_count_per_bucket)
    prepare_limit = _prepare_limit_for_target(target_count_per_bucket)
    minimum_results = _minimum_results_for_target(target_count_per_bucket)
    interactive_enrichment_limit = _interactive_enrichment_limit_for_target(target_count_per_bucket)
    interactive_backfill_limit = min(target_count_per_bucket, 3)
    interactive_search_profile = "interactive_fast" if search_depth == "fast" else "interactive"
    deep_recovery_enabled = search_depth != "fast"

    stage_started_at = time.monotonic()
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    context = extract_job_context(job.title, job.description, tags=job.tags)

    # Populate job locations for location-aware ranking
    if job.location:
        context.job_locations = normalize_job_locations(job.location)
    if context.job_locations and not job.remote:
        context.job_geo_terms = build_job_geo_terms(context.job_locations)

    recruiter_min_results = minimum_results
    manager_min_results = minimum_results
    peer_min_results = minimum_results
    recruiter_geo_terms = _bucket_geo_terms(context, bucket="recruiters") or None
    manager_geo_terms = _bucket_geo_terms(context, bucket="hiring_managers") or None
    peer_geo_terms = _bucket_geo_terms(context, bucket="peers") or None

    debug: dict[str, Any] | None = None
    if include_debug:
        debug = {
            "job": {
                "id": str(job.id),
                "title": job.title,
                "company_name": job.company_name,
                "location": job.location,
                "remote": job.remote,
                "search_depth": search_depth,
            },
            "geo": {
                "job_locations": context.job_locations,
                "job_geo_terms": context.job_geo_terms,
                "bucket_geo_terms": {
                    "recruiters": recruiter_geo_terms or [],
                    "hiring_managers": manager_geo_terms or [],
                    "peers": peer_geo_terms or [],
                },
            },
            "searches": {},
            "funnels": {},
            "final": {},
        }
    _record_timing(
        debug,
        stage="job_load_and_context",
        started_at=stage_started_at,
        company_name=job.company_name,
        interactive_enrichment_limit=interactive_enrichment_limit,
        interactive_backfill_limit=interactive_backfill_limit,
    )

    company_started_at = time.monotonic()
    company = await get_or_create_company(
        db,
        user_id,
        job.company_name,
        ats_slug=job.ats_slug,
        careers_url=job.url,
    )
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    # For ambiguous companies, resolve a domain for search disambiguation
    search_domain: str | None = None
    if is_ambiguous_company_name(job.company_name):
        search_domain = company.domain if company.domain_trusted else None
        if not search_domain:
            hints = company.identity_hints if isinstance(company.identity_hints, dict) else {}
            normalized = normalize_company_name(job.company_name)
            dr = (hints.get("domain_root") or "").strip().lower()
            if dr and dr != normalized:
                search_domain = dr
            if not search_domain:
                li_slug = (hints.get("linkedin_company_slug") or "").strip().lower()
                if li_slug and li_slug != normalized:
                    common_tlds = ("ai", "io", "co", "app", "dev", "tech", "xyz", "com", "org", "net")
                    derived_domain = None
                    if li_slug.startswith(normalized):
                        suffix = li_slug[len(normalized):]
                        if suffix in common_tlds:
                            derived_domain = f"{normalized}.{suffix}"
                    search_domain = derived_domain or li_slug
            if not search_domain:
                ch = (hints.get("careers_host") or "").strip().lower()
                if ch and not any(root in ch for root in ("lever", "greenhouse", "ashby", "workable", "workday")):
                    search_domain = ch
    _record_timing(
        debug,
        stage="company_resolution",
        started_at=company_started_at,
        company_id=str(company.id) if company.id else None,
        search_domain=search_domain,
    )
    recruiter_titles = _prioritize_titles_for_search(
        context.recruiter_titles,
        bucket="recruiters",
        context=context,
    )
    manager_titles = _initial_manager_titles(context)
    peer_titles = _prioritize_titles_for_search(
        context.peer_titles,
        bucket="peers",
        context=context,
    )

    # Build search keywords: product/team names first (most specific), then
    # generic team + domain keywords.  Product names like "Data Cloud" scope
    # searches to the right part of a large org.
    product_names = getattr(context, "product_team_names", []) or []
    search_keywords = _sanitize_search_keywords(
        product_names + context.team_keywords + context.domain_keywords,
        company_name=job.company_name,
    )

    # Run the three initial bucket searches concurrently (audit H2) to match the
    # company-level path — previously sequential, adding 6-12s of avoidable latency.
    initial_searches_started_at = time.monotonic()
    recruiter_candidates, manager_candidates, peer_candidates = await asyncio.gather(
        _search_candidates(
            job.company_name,
            titles=recruiter_titles,
            departments=context.apollo_departments,
            team_keywords=search_keywords,
            geo_terms=recruiter_geo_terms,
            public_identity_terms=public_identity_terms,
            company_domain=search_domain,
            limit=search_limit,
            min_results=recruiter_min_results,
            debug_bucket=debug["searches"].setdefault("recruiters_initial", {}) if debug is not None else None,
            search_profile=interactive_search_profile,
        ),
        _search_candidates(
            job.company_name,
            titles=manager_titles,
            departments=context.apollo_departments,
            seniority=_manager_seniority_filters(context),
            team_keywords=search_keywords,
            geo_terms=manager_geo_terms,
            public_identity_terms=public_identity_terms,
            company_domain=search_domain,
            limit=search_limit,
            min_results=manager_min_results,
            debug_bucket=debug["searches"].setdefault("hiring_managers_initial", {}) if debug is not None else None,
            search_profile=interactive_search_profile,
        ),
        _search_candidates(
            job.company_name,
            titles=peer_titles,
            departments=context.apollo_departments,
            seniority=_peer_seniority_filters(context),
            team_keywords=search_keywords,
            geo_terms=peer_geo_terms,
            public_identity_terms=public_identity_terms,
            company_domain=search_domain,
            limit=search_limit,
            min_results=peer_min_results,
            debug_bucket=debug["searches"].setdefault("peers_initial", {}) if debug is not None else None,
            search_profile=interactive_search_profile,
        ),
    )
    _record_timing(
        debug,
        stage="initial_bucket_searches",
        started_at=initial_searches_started_at,
        recruiter_candidates=len(recruiter_candidates),
        manager_candidates=len(manager_candidates),
        peer_candidates=len(peer_candidates),
    )
    # For ambiguous companies, run a broad employee discovery without title constraints
    # since title-specific queries get polluted by people sharing the company name
    if search_domain and is_ambiguous_company_name(job.company_name):
        ambiguous_search_started_at = time.monotonic()
        broad_employee_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        broad_employees = await search_router_client.search_people(
            job.company_name,
            titles=None,
            team_keywords=None,
            geo_terms=manager_geo_terms or context.job_geo_terms or None,
            limit=max(search_limit, 15),
            min_results=5,
            company_domain=search_domain,
            debug_traces=broad_employee_traces,
            search_profile=interactive_search_profile,
        )
        if debug is not None:
            debug["searches"]["ambiguous_company_broad_employees"] = {
                "provider_traces": broad_employee_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in broad_employees[:10]],
            }
        recruiter_candidates = _dedupe_candidates(recruiter_candidates, broad_employees)
        manager_candidates = _dedupe_candidates(manager_candidates, broad_employees)
        peer_candidates = _dedupe_candidates(peer_candidates, broad_employees)
        _record_timing(
            debug,
            stage="ambiguous_company_broad_employees",
            started_at=ambiguous_search_started_at,
            broad_employees=len(broad_employees),
        )

    hiring_team_traces: list[dict[str, Any]] | None = [] if debug is not None else None
    hiring_team_started_at = time.monotonic()
    hiring_team_candidates = await search_router_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        geo_terms=manager_geo_terms,
        limit=max(5, min(target_count_per_bucket + 2, 8)),
        min_results=1,
        debug_traces=hiring_team_traces,
        search_profile=interactive_search_profile,
    )
    if debug is not None:
        debug["searches"]["hiring_team_initial"] = {
            "provider_traces": hiring_team_traces or [],
            "returned_candidates": [_debug_candidate_summary(item) for item in hiring_team_candidates[:10]],
        }
    _record_timing(
        debug,
        stage="initial_hiring_team_search",
        started_at=hiring_team_started_at,
        hiring_team_candidates=len(hiring_team_candidates),
    )

    # Supplementary "actively hiring" search — looks for people who posted
    # about hiring for similar roles.  We search with "hiring" as a team
    # keyword alongside the job title keywords so the results surface
    # managers/recruiters who are actively posting about open roles.
    try:
        actively_hiring_started_at = time.monotonic()
        hiring_signal_keywords = ["hiring", "open role"]
        if context.early_career:
            hiring_signal_keywords.extend(["new grad", "hiring new grads"])
        actively_hiring_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        actively_hiring_candidates = await search_router_client.search_hiring_team(
            job.company_name,
            job.title,
            team_keywords=hiring_signal_keywords,
            geo_terms=recruiter_geo_terms or manager_geo_terms,
            limit=3,
            min_results=0,
            debug_traces=actively_hiring_traces,
            search_profile=interactive_search_profile,
        )
        for candidate in actively_hiring_candidates:
            candidate["_actively_hiring"] = True
            candidate["profile_data"] = {
                **(candidate.get("profile_data") or {}),
                "actively_hiring": True,
            }
        hiring_team_candidates = _dedupe_candidates(hiring_team_candidates, actively_hiring_candidates)

        # Req-poster search: recruiters announce the exact req title on their
        # LinkedIn feed ("I'm hiring a Senior Platform Engineer!"). A feed-post
        # match against the quoted title pins the person who owns THIS req.
        req_poster_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        req_poster_candidates = await search_router_client.search_hiring_team(
            job.company_name,
            job.title,
            team_keywords=["hiring"],
            geo_terms=None,
            limit=3,
            min_results=0,
            debug_traces=req_poster_traces,
            search_profile=interactive_search_profile,
            site_scope="posts",
        )
        for candidate in req_poster_candidates:
            candidate["_actively_hiring"] = True
            candidate["_posted_this_req"] = True
            candidate["profile_data"] = {
                **(candidate.get("profile_data") or {}),
                "actively_hiring": True,
                "posted_this_req": True,
            }
        if debug is not None:
            debug["searches"]["req_poster"] = {
                "provider_traces": req_poster_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in req_poster_candidates[:5]],
            }
        hiring_team_candidates = _dedupe_candidates(hiring_team_candidates, req_poster_candidates)
        if debug is not None:
            debug["searches"]["actively_hiring_hiring_team"] = {
                "provider_traces": actively_hiring_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in actively_hiring_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="actively_hiring_hiring_team",
            started_at=actively_hiring_started_at,
            candidates=len(actively_hiring_candidates),
        )
    except Exception:
        logger.debug("Actively-hiring supplementary search failed for %s", job.company_name, exc_info=True)

    # Second supplementary search: target linkedin.com/in profiles of engineers
    # and managers who mention hiring in their profiles or posts.  This finds
    # people like Spencer Chan (Quora) or Abhishek Sehgal (Uber) who post
    # "I'm hiring" or "join my team" — especially valuable at smaller companies
    # where engineers recruit directly.
    try:
        hiring_people_started_at = time.monotonic()
        hiring_people_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        hiring_people_candidates = await search_router_client.search_people(
            job.company_name,
            titles=["hiring", "join my team", "we're hiring"],
            team_keywords=context.team_keywords[:2],
            geo_terms=recruiter_geo_terms or manager_geo_terms,
            limit=3,
            min_results=0,
            debug_traces=hiring_people_traces,
            search_profile=interactive_search_profile,
        )
        for candidate in hiring_people_candidates:
            candidate["_actively_hiring"] = True
            candidate["profile_data"] = {
                **(candidate.get("profile_data") or {}),
                "actively_hiring": True,
            }
        hiring_team_candidates = _dedupe_candidates(hiring_team_candidates, hiring_people_candidates)
        if debug is not None:
            debug["searches"]["actively_hiring_people"] = {
                "provider_traces": hiring_people_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in hiring_people_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="actively_hiring_people_search",
            started_at=hiring_people_started_at,
            candidates=len(hiring_people_candidates),
        )
    except Exception:
        logger.debug("Hiring-people supplementary search failed for %s", job.company_name, exc_info=True)

    hiring_team_overrides = await _title_overrides_for(hiring_team_candidates)
    posting_contact_candidates = _posting_contact_candidates(job, context)
    if posting_contact_candidates and debug is not None:
        debug["searches"]["posting_contacts"] = {
            "returned_candidates": [_debug_candidate_summary(item) for item in posting_contact_candidates],
        }
    recruiter_candidates = _dedupe_candidates(posting_contact_candidates, recruiter_candidates)
    recruiter_candidates = _dedupe_candidates(
        recruiter_candidates,
        [candidate for candidate in hiring_team_candidates if _bucket_with_tiebreak(candidate, hiring_team_overrides) == "recruiter"],
    )
    manager_candidates = _dedupe_candidates(
        manager_candidates,
        [candidate for candidate in hiring_team_candidates if _bucket_with_tiebreak(candidate, hiring_team_overrides) == "hiring_manager"],
    )
    peer_candidates = _dedupe_candidates(
        peer_candidates,
        [candidate for candidate in hiring_team_candidates if _bucket_with_tiebreak(candidate, hiring_team_overrides) == "peer"],
    )
    peer_retry_started_at = time.monotonic()
    peer_candidates = await _expand_peer_candidates(
        job.company_name,
        peer_candidates,
        context=context,
        public_identity_terms=public_identity_terms,
        geo_terms=peer_geo_terms,
        company_domain=search_domain,
        limit=search_limit,
        min_results=max(peer_min_results, target_count_per_bucket),
        debug_bucket=debug["searches"].setdefault("peers_retry", {}) if debug is not None else None,
        search_profile=interactive_search_profile,
    )
    _record_timing(
        debug,
        stage="peer_retry_search",
        started_at=peer_retry_started_at,
        peer_candidates=len(peer_candidates),
    )
    saved_slug_candidates = await _saved_theorg_slug_candidates(
        db,
        user_id=user_id,
        company=company,
    )
    _merge_company_public_identity_slugs(
        company,
        job.company_name,
        _candidate_theorg_slug_candidates(
            recruiter_candidates,
            manager_candidates,
            peer_candidates,
            hiring_team_candidates,
            company_name=job.company_name,
            trusted_slugs=public_identity_terms,
        )
        + saved_slug_candidates,
    )
    public_identity_terms = effective_public_identity_slugs(
        company.name,
        company.public_identity_slugs,
        identity_hints=company.identity_hints if isinstance(company.identity_hints, dict) else None,
    ) or None

    # Recover titles for all three buckets concurrently (audit H3) — each may hit
    # The Org pages with a 20s timeout, so running them serially was a bottleneck.
    recovery_started_at = time.monotonic()
    recruiter_candidates, manager_candidates, peer_candidates = await asyncio.gather(
        _recover_candidate_titles(
            recruiter_candidates,
            company=company,
            company_name=job.company_name,
        ),
        _recover_candidate_titles(
            manager_candidates,
            company=company,
            company_name=job.company_name,
        ),
        _recover_candidate_titles(
            peer_candidates,
            company=company,
            company_name=job.company_name,
        ),
    )
    manager_candidates = _dedupe_candidates(
        manager_candidates,
        [candidate for candidate in peer_candidates if _is_senior_ic_fallback(candidate.get("title"))],
    )
    _record_timing(
        debug,
        stage="candidate_title_recovery",
        started_at=recovery_started_at,
        recruiter_candidates=len(recruiter_candidates),
        manager_candidates=len(manager_candidates),
        peer_candidates=len(peer_candidates),
    )

    # GitHub-team strategy: for engineering roles, resolve the top contributors
    # to the company repos matching this job's team keywords into named, title-
    # classified contacts. Lead/manager-titled contributors join the hiring-
    # manager bucket; ICs join peers as high-confidence "they ship this code"
    # contacts. Bounded, cached, fail-soft - never blocks the search.
    github_team_started_at = time.monotonic()
    github_team_contacts: list[dict] = []
    if _occupation_is_engineering_flavored(
        context.occupation_keys if context else None,
        department=context.department if context else None,
    ) and context and context.team_keywords:
        try:
            org = await resolve_github_org(
                job.company_name,
                company.identity_hints if isinstance(company.identity_hints, dict) else None,
            )
            if org:
                github_team_contacts = await resolve_team_contacts(
                    org, list(context.team_keywords), job.company_name
                )
        except Exception:
            logger.debug("github-team strategy failed; skipping", exc_info=True)
    if github_team_contacts:
        gh_managers = [c for c in github_team_contacts if c.get("_github_bucket_hint") == "hiring_manager"]
        gh_peers = [c for c in github_team_contacts if c.get("_github_bucket_hint") != "hiring_manager"]
        manager_candidates = _dedupe_candidates(manager_candidates, gh_managers)
        peer_candidates = _dedupe_candidates(peer_candidates, gh_peers)
        if debug is not None:
            debug["searches"]["github_team"] = {
                "org": org,
                "managers": [_debug_candidate_summary(c) for c in gh_managers],
                "peers": [_debug_candidate_summary(c) for c in gh_peers],
            }
    _record_timing(
        debug,
        stage="github_team_resolution",
        started_at=github_team_started_at,
        contacts=len(github_team_contacts),
    )

    # Non-technical leadership sources: the company's own website leadership/
    # team page (the non-tech analog of GitHub - every company publishes its
    # leaders) and executives quoted by exact title in news/PR. Both feed the
    # hiring-manager bucket and are filtered by the occupation gate downstream.
    # Especially valuable for non-engineering roles where x-ray returns only
    # engineers; bounded, cached, fail-soft.
    nontech_started_at = time.monotonic()
    site_domain = company.domain if getattr(company, "domain", None) else None
    nontech = await _gather_nontech_leaders(job.company_name, site_domain, context)
    site_leaders = nontech["site"]
    news_leaders = nontech["news"]
    footprint_leaders = nontech["footprint"]
    new_leaders = site_leaders + news_leaders + footprint_leaders
    if new_leaders:
        manager_candidates = _dedupe_candidates(manager_candidates, new_leaders)
        if debug is not None:
            debug["searches"]["company_site_leaders"] = [
                _debug_candidate_summary(c) for c in site_leaders
            ]
            debug["searches"]["news_quote_leaders"] = [
                _debug_candidate_summary(c) for c in news_leaders
            ]
            debug["searches"]["public_footprint_leaders"] = [
                _debug_candidate_summary(c) for c in footprint_leaders
            ]
    site_recruiters = await _gather_company_site_recruiters(job.company_name, site_domain)
    if site_recruiters:
        recruiter_candidates = _dedupe_candidates(recruiter_candidates, site_recruiters)
        if debug is not None:
            debug["searches"]["company_site_recruiters"] = [
                _debug_candidate_summary(c) for c in site_recruiters
            ]
    _record_timing(
        debug,
        stage="nontech_leadership_resolution",
        started_at=nontech_started_at,
        site_leaders=len(site_leaders),
        news_leaders=len(news_leaders),
        footprint_leaders=len(footprint_leaders),
    )

    scoring_started_at = time.monotonic()
    manager_candidates = _score_contextual_candidates_fast(
        manager_candidates,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
        bucket="hiring_managers",
    )
    peer_candidates = _score_contextual_candidates_fast(
        peer_candidates,
        job=job,
        context=context,
        min_relevance_score=min_relevance_score,
        bucket="peers",
    )
    _record_timing(
        debug,
        stage="contextual_scoring",
        started_at=scoring_started_at,
        manager_candidates=len(manager_candidates),
        peer_candidates=len(peer_candidates),
    )
    # Affinity + outcome priors: opportunistic, bounded, applied before prep
    # so the late ranking components see the annotations.
    try:
        profile_row = (
            await db.execute(select(Profile).where(Profile.user_id == user_id))
        ).scalar_one_or_none()
        resume_parsed = profile_row.resume_parsed if profile_row else None
        if resume_parsed:
            affinity_matches = 0
            for bucket_list in (recruiter_candidates, manager_candidates, peer_candidates):
                affinity_matches += annotate_affinity(
                    bucket_list, resume_parsed, target_company=job.company_name
                )
            if debug is not None:
                debug["affinity_matches"] = affinity_matches
        reply_priors = await load_reply_priors(db, user_id)
        if reply_priors:
            stamp_outcome_priors(recruiter_candidates, reply_priors, bucket="recruiters")
            stamp_outcome_priors(manager_candidates, reply_priors, bucket="hiring_managers")
            stamp_outcome_priors(peer_candidates, reply_priors, bucket="peers")
    except Exception:
        logger.debug("affinity/outcome annotation failed; ranking stays neutral", exc_info=True)

    prepare_started_at = time.monotonic()
    recruiter_results = _prepare_candidates(
        recruiter_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="recruiters",
        context=context,
        limit=prepare_limit,
        debug_funnel=debug["funnels"].setdefault("recruiters_initial", {}) if debug is not None else None,
    )
    manager_results = _prepare_candidates(
        manager_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="hiring_managers",
        context=context,
        limit=prepare_limit,
        debug_funnel=debug["funnels"].setdefault("hiring_managers_initial", {}) if debug is not None else None,
    )
    peer_results = _prepare_candidates(
        peer_candidates,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
        bucket="peers",
        context=context,
        limit=prepare_limit,
        debug_funnel=debug["funnels"].setdefault("peers_initial", {}) if debug is not None else None,
    )
    recruiter_results = _limit_interactive_bucket(
        recruiter_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    manager_results = _limit_interactive_bucket(
        manager_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    peer_results = _limit_interactive_bucket(
        peer_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    _record_timing(
        debug,
        stage="initial_prepare",
        started_at=prepare_started_at,
        recruiter_results=len(recruiter_results),
        manager_results=len(manager_results),
        peer_results=len(peer_results),
    )
    recruiter_targeted_recovery_needed = _should_run_recruiter_targeted_recovery(
        recruiter_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    )
    manager_geo_recovery_needed = _should_run_manager_geo_recovery(
        manager_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    )
    peer_targeted_recovery_needed = _should_run_peer_targeted_recovery(
        peer_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    )

    if deep_recovery_enabled and recruiter_targeted_recovery_needed:
        recruiter_targeted_started_at = time.monotonic()
        recruiter_targeted_trace: dict[str, Any] | None = {"provider": "tavily_direct", "queries": []} if debug is not None else None
        targeted_recruiter_candidates = await tavily_search_client.search_public_people(
            job.company_name,
            titles=_recruiter_targeted_recovery_titles(context),
            team_keywords=_recruiter_targeted_recovery_keywords(context),
            public_identity_terms=public_identity_terms,
            geo_terms=recruiter_geo_terms,
            limit=search_limit,
            debug_trace=recruiter_targeted_trace,
        )
        recruiter_candidates = _dedupe_candidates(recruiter_candidates, targeted_recruiter_candidates)
        recruiter_candidates = await _recover_candidate_titles(
            recruiter_candidates,
            company=company,
            company_name=job.company_name,
        )
        recruiter_results = _prepare_candidates(
            recruiter_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("recruiters_targeted_public", {}) if debug is not None else None,
        )
        recruiter_results = _limit_interactive_bucket(
            recruiter_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            recruiter_targeted_trace = recruiter_targeted_trace or {"provider": "tavily_direct", "queries": []}
            recruiter_targeted_trace["result_count"] = len(targeted_recruiter_candidates)
            recruiter_targeted_trace["sample_results"] = [
                _debug_candidate_summary(item) for item in targeted_recruiter_candidates[:5]
            ]
            debug["searches"]["recruiters_targeted_public"] = {
                "provider_traces": [recruiter_targeted_trace],
                "returned_candidates": [_debug_candidate_summary(item) for item in targeted_recruiter_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="recruiters_targeted_public",
            started_at=recruiter_targeted_started_at,
            candidates=len(targeted_recruiter_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="recruiters_targeted_public_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_recruiter_bucket_sufficient",
        )

    recruiter_recovery_needed = _should_run_recruiter_targeted_recovery(
        recruiter_results,
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    ) or not _has_recruiter_lead_candidate(recruiter_results)

    if deep_recovery_enabled and recruiter_recovery_needed:
        recruiter_recovery_started_at = time.monotonic()
        recruiter_profile_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        recruiter_post_traces: list[dict[str, Any]] | None = [] if debug is not None else None
        recruiter_profile_candidates = await search_router_client.search_recruiter_recovery_profiles(
            job.company_name,
            team_keywords=_recruiter_targeted_recovery_keywords(context),
            geo_terms=recruiter_geo_terms,
            limit=search_limit,
            min_results=min(target_count_per_bucket, 2),
            debug_traces=recruiter_profile_traces,
            search_profile=interactive_search_profile,
        )
        recruiter_post_candidates = await search_router_client.search_recruiter_recovery_posts(
            job.company_name,
            geo_terms=recruiter_geo_terms,
            limit=search_limit,
            min_results=1,
            debug_traces=recruiter_post_traces,
            search_profile=interactive_search_profile,
        )
        recruiter_candidates = _dedupe_candidates(
            recruiter_candidates,
            recruiter_profile_candidates,
            recruiter_post_candidates,
        )
        recruiter_candidates = await _recover_candidate_titles(
            recruiter_candidates,
            company=company,
            company_name=job.company_name,
        )
        recruiter_results = _prepare_candidates(
            recruiter_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("recruiters_recovery", {}) if debug is not None else None,
        )
        recruiter_results = _limit_interactive_bucket(
            recruiter_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            debug["searches"]["recruiters_recovery_profiles"] = {
                "provider_traces": recruiter_profile_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in recruiter_profile_candidates[:10]],
            }
            debug["searches"]["recruiters_recovery_posts"] = {
                "provider_traces": recruiter_post_traces or [],
                "returned_candidates": [_debug_candidate_summary(item) for item in recruiter_post_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="recruiters_recovery",
            started_at=recruiter_recovery_started_at,
            profile_candidates=len(recruiter_profile_candidates),
            post_candidates=len(recruiter_post_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="recruiters_recovery_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_recruiter_recovery_not_needed",
        )

    if deep_recovery_enabled and manager_geo_recovery_needed:
        manager_geo_public_started_at = time.monotonic()
        tavily_manager_trace: dict[str, Any] | None = {"provider": "tavily_direct", "queries": []} if debug is not None else None
        geo_manager_public_candidates = await tavily_search_client.search_public_people(
            job.company_name,
            titles=_manager_geo_recovery_titles(context),
            team_keywords=_manager_geo_recovery_keywords(context),
            public_identity_terms=public_identity_terms,
            geo_terms=manager_geo_terms,
            limit=search_limit,
            debug_trace=tavily_manager_trace,
        )
        manager_candidates = _dedupe_candidates(manager_candidates, geo_manager_public_candidates)
        manager_candidates = _score_contextual_candidates_fast(
            manager_candidates,
            job=job,
            context=context,
            min_relevance_score=min_relevance_score,
            bucket="hiring_managers",
        )
        manager_results = _prepare_candidates(
            manager_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("hiring_managers_geo_public", {}) if debug is not None else None,
        )
        manager_results = _limit_interactive_bucket(
            manager_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            tavily_manager_trace = tavily_manager_trace or {"provider": "tavily_direct", "queries": []}
            tavily_manager_trace["result_count"] = len(geo_manager_public_candidates)
            tavily_manager_trace["sample_results"] = [
                _debug_candidate_summary(item) for item in geo_manager_public_candidates[:5]
            ]
            debug["searches"]["hiring_managers_geo_public"] = {
                "provider_traces": [tavily_manager_trace],
                "returned_candidates": [_debug_candidate_summary(item) for item in geo_manager_public_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="hiring_managers_geo_public",
            started_at=manager_geo_public_started_at,
            candidates=len(geo_manager_public_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="hiring_managers_geo_public_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_manager_bucket_sufficient",
        )

    if deep_recovery_enabled and peer_targeted_recovery_needed:
        peer_targeted_started_at = time.monotonic()
        peer_targeted_trace: dict[str, Any] | None = {"provider": "tavily_direct", "queries": []} if debug is not None else None
        targeted_peer_candidates = await tavily_search_client.search_public_people(
            job.company_name,
            titles=_peer_targeted_recovery_titles(context),
            team_keywords=_peer_targeted_recovery_keywords(context),
            public_identity_terms=public_identity_terms,
            geo_terms=peer_geo_terms,
            limit=search_limit,
            debug_trace=peer_targeted_trace,
        )
        peer_candidates = _dedupe_candidates(peer_candidates, targeted_peer_candidates)
        peer_candidates = await _recover_candidate_titles(
            peer_candidates,
            company=company,
            company_name=job.company_name,
        )
        peer_candidates = _score_contextual_candidates_fast(
            peer_candidates,
            job=job,
            context=context,
            min_relevance_score=min_relevance_score,
            bucket="peers",
        )
        peer_results = _prepare_candidates(
            peer_candidates,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("peers_targeted_public", {}) if debug is not None else None,
        )
        peer_results = _limit_interactive_bucket(
            peer_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        if debug is not None:
            peer_targeted_trace = peer_targeted_trace or {"provider": "tavily_direct", "queries": []}
            peer_targeted_trace["result_count"] = len(targeted_peer_candidates)
            peer_targeted_trace["sample_results"] = [
                _debug_candidate_summary(item) for item in targeted_peer_candidates[:5]
            ]
            debug["searches"]["peers_targeted_public"] = {
                "provider_traces": [peer_targeted_trace],
                "returned_candidates": [_debug_candidate_summary(item) for item in targeted_peer_candidates[:10]],
            }
        _record_timing(
            debug,
            stage="peers_targeted_public",
            started_at=peer_targeted_started_at,
            candidates=len(targeted_peer_candidates),
        )
    else:
        _record_timing(
            debug,
            stage="peers_targeted_public_skipped",
            started_at=time.monotonic(),
            reason="fast_search_depth_or_peer_bucket_sufficient",
        )

    if _should_expand_with_theorg(
        job.company_name,
        {
            "recruiters": len(recruiter_results),
            "hiring_managers": len(manager_results),
            "peers": len(peer_results),
        },
        context=context,
        target_count_per_bucket=target_count_per_bucket,
    ):
        theorg_started_at = time.monotonic()
        theorg_candidates = await discover_theorg_candidates(
            company,
            company_name=job.company_name,
            context=context,
            current_counts={
                "recruiters": len(recruiter_results),
                "hiring_managers": len(manager_results),
                "peers": len(peer_results),
            },
            slug_candidates=_candidate_theorg_slug_candidates(
                recruiter_candidates,
                manager_candidates,
                peer_candidates,
                hiring_team_candidates,
                company_name=job.company_name,
                trusted_slugs=public_identity_terms,
            )
            + saved_slug_candidates,
        )
        recruiter_results = _prepare_candidates(
            _dedupe_candidates(recruiter_candidates, theorg_candidates.get("recruiters", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="recruiters",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("recruiters_with_theorg", {}) if debug is not None else None,
        )
        manager_results = _prepare_candidates(
            _dedupe_candidates(manager_candidates, theorg_candidates.get("hiring_managers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="hiring_managers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("hiring_managers_with_theorg", {}) if debug is not None else None,
        )
        peer_results = _prepare_candidates(
            _dedupe_candidates(peer_candidates, theorg_candidates.get("peers", [])),
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
            bucket="peers",
            context=context,
            limit=prepare_limit,
            debug_funnel=debug["funnels"].setdefault("peers_with_theorg", {}) if debug is not None else None,
        )
        recruiter_results = _limit_interactive_bucket(
            recruiter_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        manager_results = _limit_interactive_bucket(
            manager_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        peer_results = _limit_interactive_bucket(
            peer_results,
            target_count_per_bucket=target_count_per_bucket,
        )
        _record_timing(
            debug,
            stage="theorg_expansion",
            started_at=theorg_started_at,
            recruiter_candidates=len(theorg_candidates.get("recruiters", [])),
            manager_candidates=len(theorg_candidates.get("hiring_managers", [])),
            peer_candidates=len(theorg_candidates.get("peers", [])),
        )

    backfill_started_at = time.monotonic()
    recruiter_results = _mark_linkedin_backfill_deferred(recruiter_results)
    manager_results = _mark_linkedin_backfill_deferred(manager_results)
    peer_results = _mark_linkedin_backfill_deferred(peer_results)
    _record_timing(
        debug,
        stage="linkedin_backfill_deferred",
        started_at=backfill_started_at,
        recruiter_results=len(recruiter_results),
        manager_results=len(manager_results),
        peer_results=len(peer_results),
        deferred=True,
        interactive_backfill_limit=interactive_backfill_limit,
    )

    if deep_recovery_enabled and any(
        _needs_more_bucket_size_only(results, target_count_per_bucket=target_count_per_bucket)
        for results in (recruiter_results, manager_results, peer_results)
    ):
        fallback_started_at = time.monotonic()
        if _needs_more_bucket_size_only(recruiter_results, target_count_per_bucket=target_count_per_bucket):
            recruiter_candidates = _dedupe_candidates(
                recruiter_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_recruiter_titles(context),
                    departments=context.apollo_departments,
                    team_keywords=None,
                    geo_terms=recruiter_geo_terms,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=recruiter_min_results,
                    debug_bucket=debug["searches"].setdefault("recruiters_companywide", {}) if debug is not None else None,
                    search_profile=interactive_search_profile,
                ),
            )
            recruiter_candidates = await _recover_candidate_titles(
                recruiter_candidates,
                company=company,
                company_name=job.company_name,
            )
            recruiter_results = _prepare_candidates(
                recruiter_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="recruiters",
                context=context,
                limit=prepare_limit,
                debug_funnel=debug["funnels"].setdefault("recruiters_companywide", {}) if debug is not None else None,
            )
            recruiter_results = _limit_interactive_bucket(
                recruiter_results,
                target_count_per_bucket=target_count_per_bucket,
            )
            recruiter_results = _mark_linkedin_backfill_deferred(recruiter_results)
        if _needs_more_bucket_size_only(manager_results, target_count_per_bucket=target_count_per_bucket):
            manager_candidates = _dedupe_candidates(
                manager_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_manager_titles(context),
                    departments=context.apollo_departments,
                    seniority=_manager_seniority_filters(context),
                    team_keywords=None,
                    geo_terms=manager_geo_terms,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=manager_min_results,
                    debug_bucket=debug["searches"].setdefault("hiring_managers_companywide", {}) if debug is not None else None,
                    search_profile=interactive_search_profile,
                ),
            )
            manager_candidates = await _recover_candidate_titles(
                manager_candidates,
                company=company,
                company_name=job.company_name,
            )
            manager_candidates = _score_contextual_candidates_fast(
                manager_candidates,
                job=job,
                context=context,
                min_relevance_score=min_relevance_score,
                bucket="hiring_managers",
            )
            manager_results = _prepare_candidates(
                manager_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="hiring_managers",
                context=context,
                limit=prepare_limit,
                debug_funnel=debug["funnels"].setdefault("hiring_managers_companywide", {}) if debug is not None else None,
            )
            manager_results = _limit_interactive_bucket(
                manager_results,
                target_count_per_bucket=target_count_per_bucket,
            )
            manager_results = _mark_linkedin_backfill_deferred(manager_results)
        if _needs_more_bucket_size_only(peer_results, target_count_per_bucket=target_count_per_bucket):
            peer_candidates = _dedupe_candidates(
                peer_candidates,
                await _search_candidates(
                    job.company_name,
                    titles=_companywide_peer_titles(context),
                    departments=context.apollo_departments,
                    team_keywords=None,
                    geo_terms=peer_geo_terms,
                    public_identity_terms=public_identity_terms,
                    company_domain=search_domain,
                    limit=search_limit,
                    min_results=peer_min_results,
                    debug_bucket=debug["searches"].setdefault("peers_companywide", {}) if debug is not None else None,
                    search_profile=interactive_search_profile,
                ),
            )
            peer_candidates = await _recover_candidate_titles(
                peer_candidates,
                company=company,
                company_name=job.company_name,
            )
            peer_candidates = _score_contextual_candidates_fast(
                peer_candidates,
                job=job,
                context=context,
                min_relevance_score=min_relevance_score,
                bucket="peers",
            )
            peer_results = _prepare_candidates(
                peer_candidates,
                company_name=job.company_name,
                public_identity_slugs=public_identity_terms,
                bucket="peers",
                context=context,
                limit=prepare_limit,
                debug_funnel=debug["funnels"].setdefault("peers_companywide", {}) if debug is not None else None,
            )
            peer_results = _limit_interactive_bucket(
                peer_results,
                target_count_per_bucket=target_count_per_bucket,
            )
            peer_results = _mark_linkedin_backfill_deferred(peer_results)
        _record_timing(
            debug,
            stage="companywide_fallbacks",
            started_at=fallback_started_at,
            recruiter_results=len(recruiter_results),
            manager_results=len(manager_results),
            peer_results=len(peer_results),
        )

    final_hiring_team_traces: list[dict[str, Any]] | None = [] if debug is not None else None
    final_hiring_team_started_at = time.monotonic()
    hiring_team_results = await search_router_client.search_hiring_team(
        job.company_name,
        job.title,
        team_keywords=context.team_keywords + context.domain_keywords,
        geo_terms=manager_geo_terms,
        limit=max(3, min(target_count_per_bucket + 1, 6)),
        min_results=1,
        debug_traces=final_hiring_team_traces,
        search_profile=interactive_search_profile,
    )
    if debug is not None:
        debug["searches"]["hiring_team_final"] = {
            "provider_traces": final_hiring_team_traces or [],
            "returned_candidates": [_debug_candidate_summary(item) for item in hiring_team_results[:10]],
        }
    _record_timing(
        debug,
        stage="final_hiring_team_search",
        started_at=final_hiring_team_started_at,
        candidates=len(hiring_team_results),
    )

    validated_hiring_team_results: list[dict] = []
    for raw in hiring_team_results:
        if not _candidate_matches_company(raw, job.company_name, public_identity_terms):
            continue
        employment_status = _classify_employment_status(
            raw,
            job.company_name,
            public_identity_terms,
        )
        if employment_status == "former":
            continue
        annotated = dict(raw)
        annotated["_employment_status"] = employment_status
        annotated["_org_level"] = _classify_org_level(
            annotated.get("title", ""),
            source=annotated.get("source", ""),
            snippet=annotated.get("snippet", ""),
        )
        validated_hiring_team_results.append(annotated)

    bucket_candidate_groups = _dedupe_candidate_bucket_groups(
        {
            "recruiters": _dedupe_candidates(
                recruiter_results,
                [
                    candidate
                    for candidate in validated_hiring_team_results
                    if _classify_person(
                        candidate.get("title", ""),
                        candidate.get("source", ""),
                        candidate.get("snippet", ""),
                    ) == "recruiter"
                ],
            ),
            "hiring_managers": _dedupe_candidates(
                manager_results,
                [
                    candidate
                    for candidate in validated_hiring_team_results
                    if _classify_person(
                        candidate.get("title", ""),
                        candidate.get("source", ""),
                        candidate.get("snippet", ""),
                    ) == "hiring_manager"
                ],
            ),
            "peers": _dedupe_candidates(
                peer_results,
                [
                    candidate
                    for candidate in validated_hiring_team_results
                    if _classify_person(
                        candidate.get("title", ""),
                        candidate.get("source", ""),
                        candidate.get("snippet", ""),
                    ) == "peer"
                ],
            ),
        },
        context=context,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
    )
    recruiter_results = bucket_candidate_groups["recruiters"]
    manager_results = bucket_candidate_groups["hiring_managers"]
    peer_results = bucket_candidate_groups["peers"]
    recruiter_results = _limit_interactive_bucket(
        recruiter_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    manager_results = _limit_interactive_bucket(
        manager_results,
        target_count_per_bucket=target_count_per_bucket,
    )
    peer_results = _limit_interactive_bucket(
        peer_results,
        target_count_per_bucket=target_count_per_bucket,
    )

    bucketed = {"recruiters": [], "hiring_managers": [], "peers": []}
    seen = {"recruiters": set(), "hiring_managers": set(), "peers": set()}

    store_started_at = time.monotonic()
    for data in recruiter_results:
        person = await _store_person(db, user_id, company, data, "recruiter")
        _append_bucket(
            bucketed,
            seen,
            person,
            data,
            explicit_type="recruiter",
            context=context,
            company_name=job.company_name,
            public_identity_slugs=public_identity_terms,
        )

    for data in manager_results:
        person = await _store_person(
            db,
            user_id,
            company,
            data,
            _classify_person(data.get("title", ""), data.get("source", ""), data.get("snippet", "")),
        )
        _append_bucket(bucketed, seen, person, data, context=context, company_name=job.company_name, public_identity_slugs=public_identity_terms)

    for data in peer_results:
        person = await _store_person(db, user_id, company, data, "peer")
        _append_bucket(bucketed, seen, person, data, explicit_type="peer", context=context, company_name=job.company_name, public_identity_slugs=public_identity_terms)
    _record_timing(
        debug,
        stage="store_people",
        started_at=store_started_at,
        recruiter_results=len(recruiter_results),
        manager_results=len(manager_results),
        peer_results=len(peer_results),
    )

    verification_started_at = time.monotonic()
    await verify_people_current_company(
        bucketed,
        company_name=job.company_name,
        company_domain=company.domain if company.domain_trusted else None,
        company_public_identity_slugs=public_identity_terms,
        max_candidates=min(
            _interactive_enrichment_limit_for_target(target_count_per_bucket),
            6,
        ),
    )
    _record_timing(
        debug,
        stage="employment_verification",
        started_at=verification_started_at,
        verify_max_candidates=min(
            _interactive_enrichment_limit_for_target(target_count_per_bucket),
            6,
        ),
    )
    _backfill_sparse_hiring_manager_bucket(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
    )
    warm_paths_started_at = time.monotonic()
    your_connections = await linkedin_graph_service.get_connections_for_company(
        db,
        user_id,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
    )
    direct_connections = await linkedin_graph_service.get_connections_by_linkedin_slugs(
        db,
        user_id,
        _bucketed_linkedin_slugs(bucketed),
    )
    direct_follows = await linkedin_graph_service.get_followed_people_by_linkedin_slugs(
        db,
        user_id,
        _bucketed_linkedin_slugs(bucketed),
    )
    company_follows = await linkedin_graph_service.get_followed_companies_for_company(
        db,
        user_id,
        company_name=job.company_name,
        public_identity_slugs=public_identity_terms,
    )
    linkedin_graph_service.apply_warm_path_annotations(
        bucketed,
        company_name=job.company_name,
        your_connections=your_connections,
        direct_connections=direct_connections,
        job_title=job.title,
        department=context.department,
    )
    linkedin_graph_service.apply_follow_signal_annotations(
        bucketed,
        company_name=job.company_name,
        direct_follows=direct_follows,
        company_follows=company_follows,
    )
    _record_timing(
        debug,
        stage="warm_path_annotations",
        started_at=warm_paths_started_at,
        your_connections=len(your_connections),
        direct_connections=len(direct_connections),
        direct_follows=len(direct_follows),
        company_follows=len(company_follows),
    )
    commit_started_at = time.monotonic()
    await db.commit()
    _record_timing(debug, stage="db_commit", started_at=commit_started_at)

    # Small-company recruiter fallback: when the recruiter bucket is thin
    # (0-1 results) and the company is small/mid-size, promote hiring
    # managers and peers who have an "actively hiring" signal into the
    # recruiter bucket.  At companies with ≤500 employees, engineers and
    # managers often do the recruiting directly.
    company_size_str = (company.size or "").strip().lower()
    _small_company = (
        not company_size_str
        or any(token in company_size_str for token in ("1-", "11-", "51-", "201-", "small", "micro"))
        or (company_size_str.isdigit() and int(company_size_str) <= 500)
    )
    if _small_company and len(bucketed["recruiters"]) <= 1:
        for bucket_name in ("hiring_managers", "peers"):
            for person in bucketed[bucket_name]:
                if len(bucketed["recruiters"]) >= target_count_per_bucket:
                    break
                profile_data = getattr(person, "profile_data", None) or {}
                if profile_data.get("actively_hiring"):
                    identity_key = getattr(person, "linkedin_url", None) or getattr(person, "full_name", "")
                    if identity_key and identity_key not in seen["recruiters"]:
                        setattr(person, "fallback_reason", "Identified as actively hiring on their team (small-company recruiter fallback).")
                        bucketed["recruiters"].append(person)
                        seen["recruiters"].add(identity_key)

    filtered_bucketed = _finalize_bucketed(
        bucketed,
        target_count_per_bucket=target_count_per_bucket,
        location_terms=getattr(context, "job_geo_terms", None),
    )
    if debug is not None:
        debug["final"] = {
            "validated_hiring_team_results": [
                _debug_candidate_summary(item)
                for item in validated_hiring_team_results
            ],
            "recruiters": [_debug_person_summary(person) for person in filtered_bucketed["recruiters"]],
            "hiring_managers": [_debug_person_summary(person) for person in filtered_bucketed["hiring_managers"]],
            "peers": [_debug_person_summary(person) for person in filtered_bucketed["peers"]],
        }
        _record_timing(
            debug,
            stage="total",
            started_at=total_started_at,
            final_recruiters=len(filtered_bucketed["recruiters"]),
            final_hiring_managers=len(filtered_bucketed["hiring_managers"]),
            final_peers=len(filtered_bucketed["peers"]),
        )
    return {
        "company": company,
        "your_connections": [
            linkedin_graph_service.serialize_connection(connection)
            for connection in your_connections
        ],
        **filtered_bucketed,
        "job_context": {
            "department": context.department,
            "team_keywords": context.team_keywords,
            "seniority": context.seniority,
        },
        "debug": debug,
    }


async def enrich_person_from_linkedin(
    db: AsyncSession,
    user_id: uuid.UUID,
    linkedin_url: str,
) -> Person:
    """Enrich a single person from LinkedIn via Proxycurl."""
    from app.utils.linkedin import normalize_linkedin_url

    normalized = normalize_linkedin_url(linkedin_url) or linkedin_url

    # Try normalized URL first, fall back to raw URL
    result = await db.execute(
        select(Person).where(Person.user_id == user_id, Person.linkedin_url == normalized)
    )
    existing = result.scalar_one_or_none()
    if not existing and normalized != linkedin_url:
        result = await db.execute(
            select(Person).where(Person.user_id == user_id, Person.linkedin_url == linkedin_url)
        )
        existing = result.scalar_one_or_none()
    if existing and existing.profile_data:
        return existing

    profile = await proxycurl_client.enrich_profile(linkedin_url)

    if existing:
        existing.profile_data = profile
        if profile:
            existing.full_name = profile.get("full_name") or existing.full_name
            existing.title = profile.get("title") or existing.title
        await db.commit()
        await db.refresh(existing)
        return existing

    person_type = _classify_person(profile.get("title", "")) if profile else "peer"
    person = Person(
        user_id=user_id,
        full_name=profile.get("full_name") if profile else None,
        title=profile.get("title") if profile else None,
        linkedin_url=normalized,
        person_type=person_type,
        profile_data=profile,
        source="proxycurl" if profile else "manual",
    )
    db.add(person)
    await db.commit()
    await db.refresh(person)
    return person
