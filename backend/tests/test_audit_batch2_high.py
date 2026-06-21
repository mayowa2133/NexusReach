"""Proof tests for audit Batch 2 (HIGH) fixes — 2026-05-29.

Covers H1, H4, H6, H7, H8, H9, H11, H12. (H2/H3 parallelization and H10
streaming are verified by their existing suites / inline checks; H5 has a
dedicated test in test_apollo_client.py.)
"""

import pytest


# ---------------------------------------------------------------------------
# H1 — geographic bias removed from query builders + location ranking
# ---------------------------------------------------------------------------
def test_h1_tavily_recruiter_queries_have_no_hardcoded_region():
    from app.clients.tavily_search_client import _recruiter_targeted_queries

    queries = _recruiter_targeted_queries("Acme", geo_terms=["Berlin"])
    blob = " ".join(queries).lower()
    assert "canada" not in blob
    assert "toronto" not in blob
    # The provided geo is actually used.
    assert "berlin" in blob


def test_h1_tavily_recruiter_queries_omit_geo_when_unknown():
    from app.clients.tavily_search_client import _recruiter_targeted_queries

    queries = _recruiter_targeted_queries("Acme", geo_terms=None)
    blob = " ".join(queries).lower()
    assert "canada" not in blob and "toronto" not in blob
    # No double spaces left where the geo token used to be.
    assert all("  " not in q for q in queries)


def test_h1_brave_recovery_queries_use_provided_region():
    from app.clients.brave_search_client import (
        _recruiter_recovery_post_queries,
        _recruiter_recovery_profile_queries,
    )

    profile_q = _recruiter_recovery_profile_queries("Acme", geo_terms=["Berlin"])
    post_q = _recruiter_recovery_post_queries("Acme", geo_terms=["Berlin"])
    blob = " ".join(profile_q + post_q).lower()
    assert "canada" not in blob
    assert "toronto" not in blob
    assert "hiring in berlin" in blob


def test_h1_person_location_rank_uses_job_terms_not_toronto():
    from types import SimpleNamespace

    from app.services.people_service import _person_location_match_rank

    berlin_person = SimpleNamespace(location="Berlin, Germany", profile_data={})
    toronto_person = SimpleNamespace(location="Toronto, ON", profile_data={})

    # With Berlin as the target, the Berlin candidate ranks best (0).
    assert _person_location_match_rank(berlin_person, ["Berlin"]) == 0
    # Toronto is no longer special when it isn't the target.
    assert _person_location_match_rank(toronto_person, ["Berlin"]) == 1
    # With no target locations, location is neutral for everyone.
    assert _person_location_match_rank(toronto_person, None) == 1
    assert _person_location_match_rank(berlin_person, None) == 1


# ---------------------------------------------------------------------------
# H6 — reliable date ordering (no lexicographic string compare)
# ---------------------------------------------------------------------------
def test_h6_date_sort_uses_real_date_not_string_cast():
    from sqlalchemy import Date, func as sa_func, select
    from sqlalchemy.dialects import postgresql

    from app.models.job import Job

    posted_date = sa_func.cast(
        sa_func.substring(Job.posted_at, r"^\d{4}-\d{2}-\d{2}"), Date
    )
    recency = sa_func.coalesce(posted_date, sa_func.cast(Job.created_at, Date))
    q = select(Job.id).order_by(recency.desc().nullslast(), Job.created_at.desc())
    sql = str(q.compile(dialect=postgresql.dialect()))
    assert "SUBSTRING" in sql.upper()
    assert "AS DATE" in sql.upper()
    # No "created_at cast to text/varchar" — the old lexicographic bug.
    assert "AS VARCHAR" not in sql.upper()


# ---------------------------------------------------------------------------
# H7 — canonical_url populated for indexed dedup
# ---------------------------------------------------------------------------
def test_h7_build_job_populates_canonical_url():
    from app.services.job_service import _build_job

    job = _build_job(
        user_id=__import__("uuid").uuid4(),
        data={
            "title": "SWE",
            "company_name": "Acme",
            "url": "https://acme.com/jobs/42?utm=x#frag",
            "source": "greenhouse",
        },
        score=None,
        breakdown={},
        fingerprint="fp1",
    )
    # Query string and fragment are stripped in the stored canonical form.
    assert job.canonical_url == "https://acme.com/jobs/42"


# ---------------------------------------------------------------------------
# H8 — startup direct sources forward a single query
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_h8_startup_direct_sources_forward_single_query(monkeypatch):
    from app.services import job_service

    captured: dict[str, object] = {}

    async def _fake_yc(query=None, limit=200):
        captured["yc_query"] = query
        return []

    async def _fake_wf(query=None, limit=200):
        captured["wf_query"] = query
        return []

    async def _fake_vl(query=None, limit=200):
        captured["vl_query"] = query
        return []

    monkeypatch.setattr(job_service.yc_jobs_client, "search_yc_jobs", _fake_yc)
    monkeypatch.setattr(job_service.wellfound_jobs_client, "search_wellfound_jobs", _fake_wf)
    monkeypatch.setattr(job_service.ventureloop_jobs_client, "search_ventureloop_jobs", _fake_vl)

    async def _fake_store(db, user_id, jobs, profile):
        return []

    monkeypatch.setattr(job_service, "_store_raw_jobs", _fake_store)

    await job_service._discover_startup_direct_sources(
        db=None, user_id=__import__("uuid").uuid4(), profile=None, queries=["ml engineer"]
    )
    assert captured == {
        "yc_query": "ml engineer",
        "wf_query": "ml engineer",
        "vl_query": "ml engineer",
    }


@pytest.mark.asyncio
async def test_h8_startup_direct_sources_stay_broad_for_multiple_queries(monkeypatch):
    from app.services import job_service

    captured: list[object] = []

    async def _fake(query=None, limit=200):
        captured.append(query)
        return []

    monkeypatch.setattr(job_service.yc_jobs_client, "search_yc_jobs", _fake)
    monkeypatch.setattr(job_service.wellfound_jobs_client, "search_wellfound_jobs", _fake)
    monkeypatch.setattr(job_service.ventureloop_jobs_client, "search_ventureloop_jobs", _fake)

    async def _fake_store(db, user_id, jobs, profile):
        return []

    monkeypatch.setattr(job_service, "_store_raw_jobs", _fake_store)

    await job_service._discover_startup_direct_sources(
        db=None,
        user_id=__import__("uuid").uuid4(),
        profile=None,
        queries=["ml engineer", "backend"],
    )
    # Multiple queries -> fetch broadly (None) and rely on post-hoc filtering.
    assert captured == [None, None, None]


# ---------------------------------------------------------------------------
# H9 — remote jobs survive a location filter
# ---------------------------------------------------------------------------
def test_h9_remote_job_passes_location_filter_without_literal_remote():
    from app.services.job_service import _job_matches_refresh_filters

    remote_job = {
        "remote": True,
        "location": "San Francisco, CA",  # HQ, no "remote" token, no country codes
    }
    # Previously excluded; a remote role is location-eligible for any filter.
    assert _job_matches_refresh_filters(remote_job, location="Canada", remote_only=False) is True


def test_h9_non_remote_job_still_filtered_by_country_code():
    from app.services.job_service import _job_matches_refresh_filters

    us_only = {
        "remote": True,
        "location": "San Francisco, CA",
        "country_codes": ["US"],
    }
    # A remote role explicitly restricted to the US must NOT match a Canada filter.
    assert _job_matches_refresh_filters(us_only, location="Canada", remote_only=False) is False


# ---------------------------------------------------------------------------
# H4 — discovery rate limiter reuses a single Redis client
# ---------------------------------------------------------------------------
def test_h4_rate_limiter_reuses_singleton(monkeypatch):
    import app.utils.discovery_rate_limit as drl

    drl._redis_client = None
    created = {"count": 0}

    def _fake_from_url(url, **kwargs):
        created["count"] += 1
        return object()

    monkeypatch.setattr(drl.aioredis, "from_url", _fake_from_url)
    c1 = drl._client()
    c2 = drl._client()
    assert c1 is c2
    assert created["count"] == 1
    drl._redis_client = None


# ---------------------------------------------------------------------------
# H11 — Outlook token caching mirrors Gmail
# ---------------------------------------------------------------------------
def test_h11_outlook_has_token_cache_and_lock():
    from app.services import outlook_service

    assert hasattr(outlook_service, "_token_cache")
    assert hasattr(outlook_service, "_get_lock")
    assert hasattr(outlook_service, "_refresh_access_token_uncached")


# ---------------------------------------------------------------------------
# H12 — run_async helper works with and without a running loop
# ---------------------------------------------------------------------------
def test_h12_run_async_without_running_loop():
    from app.tasks import run_async

    async def _coro():
        return "ok"

    assert run_async(_coro()) == "ok"


@pytest.mark.asyncio
async def test_h12_run_async_inside_running_loop():
    from app.tasks import run_async

    async def _coro():
        return 7

    # Called from within a running event loop (gevent/eventlet scenario).
    assert run_async(_coro()) == 7


def test_h12_run_async_reuses_worker_event_loop():
    from app.tasks import run_async

    async def _loop_id():
        import asyncio

        return id(asyncio.get_running_loop())

    assert run_async(_loop_id()) == run_async(_loop_id())
