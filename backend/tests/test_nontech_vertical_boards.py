"""Tests for curated non-tech vertical boards (Workday health systems,
universities, banks/insurers, retailers) and their occupation routing."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients import workday_client
from app.services import job_service

pytestmark = pytest.mark.asyncio

_KNOWN_VERTICALS = {"healthcare", "education", "finance", "retail"}


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------

def test_nontech_registry_well_formed():
    companies = workday_client.WORKDAY_NONTECH_COMPANIES
    assert companies, "registry should not be empty"
    seen: set[str] = set()
    for c in companies:
        for field in ("label", "company", "wd", "site", "vertical"):
            assert c.get(field), f"{c.get('label')} missing {field}"
        assert c["vertical"] in _KNOWN_VERTICALS, f"{c['label']} unknown vertical {c['vertical']}"
        assert c["wd"].startswith("wd"), f"{c['label']} bad wd tier {c['wd']}"
        # no duplicate employer tenant
        key = f"{c['company']}/{c['site']}"
        assert key not in seen, f"duplicate tenant {key}"
        seen.add(key)


def test_nontech_registry_covers_each_vertical():
    verticals = {c["vertical"] for c in workday_client.WORKDAY_NONTECH_COMPANIES}
    assert verticals == _KNOWN_VERTICALS


# ---------------------------------------------------------------------------
# Occupation -> vertical routing
# ---------------------------------------------------------------------------

def test_verticals_for_occupations():
    f = job_service.verticals_for_occupations
    assert f(["healthcare"]) == {"healthcare"}
    assert f(["education_training"]) == {"education"}
    assert f(["accounting_finance"]) == {"finance"}
    assert f(["sales"]) == {"finance", "retail"}
    assert f(["supply_chain"]) == {"retail"}
    # engineering / unmapped occupations pull no vertical boards
    assert f(["software_engineering"]) == set()
    assert f([]) == set()
    assert f(None) == set()
    # union across multiple occupations
    assert f(["healthcare", "accounting_finance"]) == {"healthcare", "finance"}


def test_every_mapped_vertical_has_employers():
    """Each vertical an occupation can route to must have at least one employer."""
    available = {c["vertical"] for c in workday_client.WORKDAY_NONTECH_COMPANIES}
    for verticals in job_service.OCCUPATION_VERTICALS.values():
        for v in verticals:
            assert v in available, f"occupation maps to {v} but no employer exists"


# ---------------------------------------------------------------------------
# Vertical-filtered fetch
# ---------------------------------------------------------------------------

async def test_discover_all_nontech_workday_filters_by_vertical():
    captured: dict = {}

    async def fake_discover(companies, search_text="", limit_per_company=20):
        captured["companies"] = companies
        return [{"title": "x"} for _ in companies]

    with patch.object(workday_client, "discover_workday_companies", new=fake_discover):
        await workday_client.discover_all_nontech_workday(verticals={"healthcare"})

    assert captured["companies"], "should fetch the healthcare subset"
    assert all(c["vertical"] == "healthcare" for c in captured["companies"])


async def test_discover_all_nontech_workday_no_filter_fetches_all():
    captured: dict = {}

    async def fake_discover(companies, search_text="", limit_per_company=20):
        captured["companies"] = companies
        return []

    with patch.object(workday_client, "discover_workday_companies", new=fake_discover):
        await workday_client.discover_all_nontech_workday()  # verticals=None

    assert len(captured["companies"]) == len(workday_client.WORKDAY_NONTECH_COMPANIES)


# ---------------------------------------------------------------------------
# _discover_nontech_vertical_boards
# ---------------------------------------------------------------------------

async def test_discover_nontech_vertical_boards_empty_skips_fetch():
    with patch.object(
        workday_client, "discover_all_nontech_workday", new=AsyncMock()
    ) as mock_fetch:
        n = await job_service._discover_nontech_vertical_boards(
            MagicMock(), uuid.uuid4(), set(), None
        )
    assert n == 0
    mock_fetch.assert_not_awaited()


async def test_discover_nontech_vertical_boards_fetches_and_stores():
    raw = [{"title": "RN"}, {"title": "Nurse Manager"}]
    with (
        patch.object(
            workday_client,
            "discover_all_nontech_workday",
            new=AsyncMock(return_value=raw),
        ) as mock_fetch,
        patch.object(
            job_service, "_store_raw_jobs", new=AsyncMock(return_value=raw)
        ) as mock_store,
    ):
        n = await job_service._discover_nontech_vertical_boards(
            MagicMock(), uuid.uuid4(), {"healthcare"}, None
        )
    assert n == 2
    mock_fetch.assert_awaited_once()
    assert mock_fetch.await_args.kwargs["verticals"] == {"healthcare"}
    mock_store.assert_awaited_once()


async def test_discover_nontech_vertical_boards_fails_soft():
    with (
        patch.object(
            workday_client,
            "discover_all_nontech_workday",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch.object(job_service, "_store_raw_jobs", new=AsyncMock()) as mock_store,
    ):
        n = await job_service._discover_nontech_vertical_boards(
            MagicMock(), uuid.uuid4(), {"finance"}, None
        )
    assert n == 0
    mock_store.assert_not_awaited()


# ---------------------------------------------------------------------------
# discover_jobs integration: occupation routing
# ---------------------------------------------------------------------------

def _mock_db(profile):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db.execute = AsyncMock(return_value=result)
    return db


async def test_discover_jobs_routes_healthcare_to_vertical_boards():
    profile = MagicMock()
    profile.target_occupations = ["healthcare"]
    profile.target_roles = None
    profile.target_locations = []

    with (
        patch.object(job_service, "search_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service.newgrad_jobs_client, "search_newgrad_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_store_raw_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_discover_ats_boards", new=AsyncMock(return_value=0)) as mock_ats,
        patch.object(job_service, "_discover_nontech_vertical_boards", new=AsyncMock(return_value=5)) as mock_vert,
    ):
        await job_service.discover_jobs(_mock_db(profile), uuid.uuid4())

    # tech ATS boards skipped (healthcare is industry-bound non-tech) ...
    mock_ats.assert_not_awaited()
    # ... but the healthcare vertical boards are pulled
    mock_vert.assert_awaited_once()
    assert mock_vert.await_args.args[2] == {"healthcare"}


async def test_discover_jobs_engineering_skips_vertical_boards():
    profile = MagicMock()
    profile.target_occupations = ["software_engineering"]
    profile.target_roles = None
    profile.target_locations = []

    with (
        patch.object(job_service, "search_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service.newgrad_jobs_client, "search_newgrad_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_store_raw_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_discover_ats_boards", new=AsyncMock(return_value=0)) as mock_ats,
        patch.object(job_service, "_discover_nontech_vertical_boards", new=AsyncMock(return_value=0)) as mock_vert,
    ):
        await job_service.discover_jobs(_mock_db(profile), uuid.uuid4())

    # engineers keep the tech ATS boards and pull no non-tech vertical boards
    mock_ats.assert_awaited_once()
    mock_vert.assert_not_awaited()


async def test_discover_jobs_finance_keeps_tech_and_adds_finance_vertical():
    profile = MagicMock()
    profile.target_occupations = ["accounting_finance"]
    profile.target_roles = None
    profile.target_locations = []

    with (
        patch.object(job_service, "search_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service.newgrad_jobs_client, "search_newgrad_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_store_raw_jobs", new=AsyncMock(return_value=[])),
        patch.object(job_service, "_discover_ats_boards", new=AsyncMock(return_value=0)) as mock_ats,
        patch.object(job_service, "_discover_nontech_vertical_boards", new=AsyncMock(return_value=3)) as mock_vert,
    ):
        await job_service.discover_jobs(_mock_db(profile), uuid.uuid4())

    # finance is cross-industry: tech boards stay AND finance vertical added
    mock_ats.assert_awaited_once()
    mock_vert.assert_awaited_once()
    assert mock_vert.await_args.args[2] == {"finance"}
