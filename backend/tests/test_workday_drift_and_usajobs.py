"""Tests for Workday config drift verification/auto-repair and the USAJobs client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.clients import usajobs_client, workday_client

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Workday config drift verification + auto-repair
# ---------------------------------------------------------------------------

async def test_verify_config_ok():
    entry = {"label": "Acme U", "company": "acme", "wd": "wd1", "site": "Careers", "vertical": "education"}
    with patch.object(workday_client, "_probe_config", new=AsyncMock(return_value=123)):
        r = await workday_client.verify_workday_config(entry)
    assert r["status"] == "ok"
    assert r["wd"] == "wd1"
    assert r["total"] == 123


async def test_verify_config_repaired_on_tier_drift():
    entry = {"label": "Acme U", "company": "acme", "wd": "wd1", "site": "Careers", "vertical": "education"}

    async def fake_probe(company, wd, site):
        return 50 if wd == "wd5" else None  # configured wd1 dead, wd5 works

    with patch.object(workday_client, "_probe_config", new=fake_probe):
        r = await workday_client.verify_workday_config(entry)
    assert r["status"] == "repaired"
    assert r["old_wd"] == "wd1"
    assert r["wd"] == "wd5"
    assert r["total"] == 50


async def test_verify_config_dead_when_no_tier_works():
    entry = {"label": "Acme U", "company": "acme", "wd": "wd1", "site": "Careers", "vertical": "education"}
    with patch.object(workday_client, "_probe_config", new=AsyncMock(return_value=None)):
        r = await workday_client.verify_workday_config(entry)
    assert r["status"] == "dead"


async def test_verify_config_no_repair_flag():
    entry = {"label": "Acme U", "company": "acme", "wd": "wd1", "site": "Careers"}

    async def fake_probe(company, wd, site):
        return 50 if wd == "wd5" else None

    with patch.object(workday_client, "_probe_config", new=fake_probe):
        r = await workday_client.verify_workday_config(entry, repair=False)
    assert r["status"] == "dead"  # repair disabled, configured tier dead


async def test_verify_all_workday_runs_over_registry():
    reg = [
        {"label": "A", "company": "a", "wd": "wd1", "site": "X", "vertical": "finance"},
        {"label": "B", "company": "b", "wd": "wd5", "site": "Y", "vertical": "retail"},
    ]
    with patch.object(workday_client, "_probe_config", new=AsyncMock(return_value=10)):
        results = await workday_client.verify_all_workday(reg)
    assert len(results) == 2
    assert all(r["status"] == "ok" for r in results)


def test_registry_has_no_obvious_duplicates_across_tech_and_nontech():
    """A company tenant should not appear in both registries."""
    tech = {(c["company"], c["site"]) for c in workday_client.WORKDAY_COMPANIES}
    nontech = {(c["company"], c["site"]) for c in workday_client.WORKDAY_NONTECH_COMPANIES}
    assert tech.isdisjoint(nontech)


# ---------------------------------------------------------------------------
# USAJobs client (gated, fail-soft)
# ---------------------------------------------------------------------------

def _usajobs_item(title="Policy Analyst", org="Department of State", control="123"):
    return {
        "MatchedObjectId": control,
        "MatchedObjectDescriptor": {
            "PositionTitle": title,
            "OrganizationName": org,
            "PositionLocationDisplay": "Washington, DC",
            "PositionURI": "https://www.usajobs.gov/job/123",
            "ApplyURI": ["https://www.usajobs.gov/job/123/apply"],
            "PublicationStartDate": "2026-06-01",
            "UserArea": {"Details": {"JobSummary": "Analyze policy."}},
        },
    }


async def test_usajobs_unconfigured_returns_empty():
    with patch.object(usajobs_client, "settings") as s:
        s.usajobs_api_key = ""
        s.usajobs_user_agent = ""
        assert await usajobs_client.search_usajobs("nurse") == []
        assert await usajobs_client.discover_usajobs(["nurse"]) == []


async def test_usajobs_normalizes_results_when_configured():
    payload = {"SearchResult": {"SearchResultItems": [_usajobs_item(), _usajobs_item(control="456", title="Program Specialist")]}}

    class FakeResp:
        status_code = 200

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    with (
        patch.object(usajobs_client, "settings") as s,
        patch.object(usajobs_client.httpx, "AsyncClient", FakeClient),
    ):
        s.usajobs_api_key = "key"
        s.usajobs_user_agent = "me@example.com"
        jobs = await usajobs_client.search_usajobs("policy analyst", location="Washington")

    assert len(jobs) == 2
    j = jobs[0]
    assert j["source"] == "usajobs"
    assert j["external_id"] == "usajobs_123"
    assert j["title"] == "Policy Analyst"
    assert j["company_name"] == "Department of State"
    assert j["apply_url"].endswith("/apply")
    assert j["posted_at"] == "2026-06-01"


async def test_usajobs_fails_soft_on_http_error():
    class FakeResp:
        status_code = 500

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    with (
        patch.object(usajobs_client, "settings") as s,
        patch.object(usajobs_client.httpx, "AsyncClient", FakeClient),
    ):
        s.usajobs_api_key = "key"
        s.usajobs_user_agent = "me@example.com"
        assert await usajobs_client.search_usajobs("nurse") == []


def test_usajobs_normalize_item_drops_titleless():
    assert usajobs_client._normalize_item({"MatchedObjectDescriptor": {}}) is None


# ---------------------------------------------------------------------------
# Weekly health-check task
# ---------------------------------------------------------------------------

async def test_verify_curated_boards_task_summarizes_and_logs():
    from app.tasks import jobs as jobs_task

    results = [
        {"label": "OK Co", "company": "ok", "wd": "wd1", "site": "S", "status": "ok", "total": 5},
        {"label": "Drift Co", "company": "d", "wd": "wd5", "old_wd": "wd1", "site": "S", "status": "repaired", "total": 9},
        {"label": "Dead Co", "company": "x", "wd": "wd1", "site": "S", "status": "dead", "total": 0},
    ]
    with patch.object(jobs_task.workday_client, "verify_all_workday",
                      new=AsyncMock(return_value=results)):
        summary = await jobs_task._verify_curated_boards()
    assert summary == {"ok": 1, "repairable": 1, "dead": 1}
