"""Tests for the occupation gate + non-engineering context de-pollution."""

from __future__ import annotations

import pytest

from app.services.people.candidates import _prepare_candidates
from app.services.people.occupation_gate import (
    job_function_group,
    occupation_conflict,
    occupation_function_distance,
    title_function_group,
)
from app.utils.job_context import extract_job_context

pytestmark = pytest.mark.asyncio


def test_title_function_group():
    assert title_function_group("Engineering Manager") == "technical"
    assert title_function_group("Account Executive") == "gtm"
    assert title_function_group("Director of Sales") == "gtm"
    assert title_function_group("Finance Manager") == "corporate"
    assert title_function_group("Product Designer") == "creative"
    # recruiters are cross-functional -> no group
    assert title_function_group("Technical Recruiter") is None
    # generic / unrecognized -> no group
    assert title_function_group("Manager") is None
    assert title_function_group("") is None


def test_job_function_group():
    assert job_function_group(["sales"], "sales") == "gtm"
    assert job_function_group(["software_engineering"], "engineering") == "technical"
    assert job_function_group(["accounting_finance"], "finance") == "corporate"
    # multi-group occupation set -> no gate
    assert job_function_group(["sales", "software_engineering"], None) is None
    assert job_function_group([], None) is None


def test_occupation_conflict_is_conservative():
    # cross-group: engineering manager for a sales req -> conflict
    assert occupation_conflict(["sales"], "sales", "Engineering Manager") is True
    # same group: engineering manager for an engineering req -> no conflict
    assert occupation_conflict(["software_engineering"], "engineering", "Engineering Manager") is False
    # tech-internal adjacency: security req can keep an engineering manager
    assert occupation_conflict(["cybersecurity"], "security", "Engineering Manager") is False
    # same group gtm: sales director for sales req -> no conflict
    assert occupation_conflict(["sales"], "sales", "Director of Sales") is False
    # ambiguous candidate title -> never conflicts
    assert occupation_conflict(["sales"], "sales", "Manager") is False
    # unknown job group -> never conflicts
    assert occupation_conflict([], None, "Engineering Manager") is False


def test_hierarchical_function_distance_distinguishes_adjacent_from_same_group():
    assert occupation_function_distance(
        ["sales"], "sales", "Account Executive"
    ) == (0, "exact_occupation")
    assert occupation_function_distance(
        ["sales"], "sales", "Marketing Manager"
    ) == (1, "adjacent_occupation")
    assert occupation_function_distance(
        ["sales"], "sales", "Customer Success Manager"
    ) == (1, "adjacent_occupation")
    assert occupation_function_distance(
        ["sales"], "sales", "Software Engineer"
    ) == (3, "cross_function")
    assert occupation_function_distance(
        ["sales"], "sales", "Manager"
    ) == (4, "unknown")


def test_gate_rejects_offfunction_keeps_same_function():
    sales_ctx = extract_job_context(
        "Account Executive, Strategic Accounts",
        "Own the full sales cycle with strategic enterprise accounts.",
    )
    em = {
        "full_name": "Aaron Myers", "title": "Engineering Manager", "source": "brave_search",
        "snippet": "Engineering Manager at Airtable", "_employment_status": "current",
        "profile_data": {"company_match_confidence": "strong_signal"},
    }
    sales_dir = {
        "full_name": "Pat Sales", "title": "Director of Strategic Accounts", "source": "brave_search",
        "snippet": "Director of Strategic Accounts at Airtable", "_employment_status": "current",
        "profile_data": {"company_match_confidence": "strong_signal"},
    }
    kept = _prepare_candidates(
        [em, sales_dir], company_name="Airtable", public_identity_slugs=["airtable"],
        bucket="hiring_managers", context=sales_ctx, limit=5,
    )
    names = [c["full_name"] for c in kept]
    assert "Aaron Myers" not in names      # engineer rejected from sales bucket
    assert "Pat Sales" in names            # sales leader kept


def test_gate_skipped_for_captured_and_github_contacts():
    sales_ctx = extract_job_context("Account Executive", "Sell to enterprise accounts.")
    # a hiring-team-captured contact bypasses the gate (LinkedIn attached them)
    captured = {
        "full_name": "Captured Person", "title": "Engineering Manager", "source": "linkedin_hiring_team",
        "snippet": "Named on the hiring team", "_hiring_team_capture": True,
        "_employment_status": "current",
        "profile_data": {"company_match_confidence": "verified"},
    }
    kept = _prepare_candidates(
        [captured], company_name="Acme", public_identity_slugs=["acme"],
        bucket="hiring_managers", context=sales_ctx, limit=5,
    )
    assert [c["full_name"] for c in kept] == ["Captured Person"]


def test_noneng_context_uses_occupation_seeds():
    ctx = extract_job_context(
        "Account Executive, Strategic Accounts",
        "Airtable is a platform. Own the full sales cycle with strategic accounts and "
        "build relationships with VP and C-level stakeholders.",
    )
    assert ctx.occupation_keys == ["sales"]
    # engineering scaffolding gone
    assert "platform" not in ctx.team_keywords
    # no engineering scaffolding (Platform Lead / Engineer); "Sales Engineer"
    # is a legitimate sales seed and is allowed.
    assert not any("platform" in t.lower() for t in ctx.manager_titles)
    assert not any("platform" in t.lower() for t in ctx.peer_titles)
    assert not any(t.lower() in ("software engineer", "platform engineer", "engineering manager") for t in ctx.peer_titles)
    # sales seeds present
    assert any("Sales" in t for t in ctx.manager_titles)
    assert any("Account Executive" in t for t in ctx.peer_titles)
    # recruiter titles no longer lead with "Technical Recruiter"
    assert "technical" not in ctx.recruiter_titles[0].lower()


def test_engineering_context_unchanged():
    ctx = extract_job_context(
        "Senior Backend Engineer",
        "Build distributed payment systems on our platform team.",
    )
    assert "software_engineering" in ctx.occupation_keys
    # engineering roles still get engineering manager seeds
    assert any("Engineer" in t or "Engineering" in t or "Lead" in t for t in ctx.manager_titles)


def test_all_occupations_grouped_sensibly():
    """Every occupation maps to a sensible function group (or None), and no
    occupation is mislabeled 'technical' via the department fallback."""
    from app.services.occupation_taxonomy import OCCUPATIONS
    from app.services.people.occupation_gate import job_function_group

    expected_none = {"management_executive", "public_sector_government"}
    for occ in OCCUPATIONS:
        grp = job_function_group([occ.key], occ.department_bucket)
        if occ.key in expected_none:
            assert grp is None, f"{occ.key} should be ungated, got {grp}"
        else:
            assert grp in {"technical", "gtm", "corporate", "creative", "domain"}, \
                f"{occ.key} got unexpected group {grp}"


def test_cross_function_rejection_per_group():
    """Each non-technical group rejects a clearly different function."""
    from app.services.people.occupation_gate import occupation_conflict

    cases = [
        (["accounting_finance"], "finance", "Sales Director", True),
        (["marketing"], "marketing", "Software Engineer", True),
        (["healthcare"], "healthcare", "Account Executive", True),
        (["creatives_design"], "design", "Sales Manager", True),
        (["sales"], "sales", "Marketing Manager", False),   # both gtm
        (["data_analyst"], "data", "Engineering Manager", False),  # both technical
        (["management_executive"], "executive", "Engineering Manager", False),  # ungated
    ]
    for keys, dept, cand, expected in cases:
        assert occupation_conflict(keys, dept, cand) is expected, f"{keys[0]} vs {cand}"
