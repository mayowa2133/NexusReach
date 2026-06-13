"""Tests for the GitHub-team people-discovery strategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.people import github_team
from app.services.people.github_team_rank import github_team_rank

pytestmark = pytest.mark.asyncio


def test_looks_like_real_name():
    f = github_team._looks_like_real_name
    assert f("Bill Finn", "billfinn-stripe") is True
    assert f("danwaters-stripe", "danwaters-stripe") is False  # login as name
    assert f("chander", "chander-stripe") is False  # single token
    assert f(None, "x-stripe") is False


def test_company_evidenced_gate():
    g = github_team._company_evidenced
    # LinkedIn names the company -> kept
    assert g("Engineering Manager", "Team leader at Stripe", "Stripe") is True
    # LinkedIn names a different employer -> dropped
    assert g("Engineering Manager", "Engineering Manager at Datadog", "Stripe") is False
    # no LinkedIn evidence at all -> kept (GitHub-org contribution stands)
    assert g("", "", "Stripe") is True


def test_github_team_rank_favors_members():
    assert github_team_rank({"_github_team_member": True}) == 0
    assert github_team_rank({}) == 1


async def test_resolve_team_contacts_classifies_lead_vs_ic():
    contributors = [
        {"login": "billfinn-stripe", "name": "Bill Finn", "_github_contributions": 18, "team_repo": "stripe-terminal-android", "github_url": "u"},
        {"login": "danwaters-stripe", "name": None, "_github_contributions": 38, "team_repo": "stripe-terminal-android", "github_url": "u"},
        {"login": "ugochukwu-stripe", "name": "Ugochukwu Chukwu", "_github_contributions": 14, "team_repo": "stripe-terminal-android", "github_url": "u"},
        {"login": "dependabot[bot]", "name": "dependabot", "_github_contributions": 99, "team_repo": "x", "github_url": "u"},
    ]

    with (
        patch.object(github_team.github_client, "search_team_contributors", new=AsyncMock(return_value=contributors)),
        patch.object(github_team, "_resolve_linkedin", new=AsyncMock(side_effect=lambda n, c, tk: (
            (lambda r: (r[0]["title"], r[0]["snippet"], r[0]["linkedin_url"]) if r else ("", "", None))(
                {"Bill Finn": [{"title": "Stripe", "snippet": "Polyglot software engineer and team leader at Stripe", "linkedin_url": "li/bill"}],
                 "Ugochukwu Chukwu": [{"title": "Senior Software Engineer", "snippet": "Android engineer at Stripe", "linkedin_url": "li/ugo"}]}.get(n, [])
            )
        ))),
    ):
        contacts = await github_team.resolve_team_contacts(
            "stripe", ["terminal", "android"], "Stripe", limit=6
        )

    by_name = {c["full_name"]: c for c in contacts}
    # dependabot dropped (bot); danwaters dropped (no real name -> no LinkedIn)
    assert "dependabot" not in by_name
    assert "danwaters-stripe" not in by_name
    # Bill Finn "team leader" -> hiring_manager bucket
    assert by_name["Bill Finn"]["_github_bucket_hint"] == "hiring_manager"
    # Ugochukwu (Senior SWE) -> peer
    assert by_name["Ugochukwu Chukwu"]["_github_bucket_hint"] == "peer"
    # all carry team-member evidence
    assert all(c["_github_team_member"] for c in contacts)
    assert by_name["Bill Finn"]["profile_data"]["company_match_confidence"] == "strong_signal"


async def test_resolve_team_contacts_fails_soft():
    with patch.object(
        github_team.github_client, "search_team_contributors",
        new=AsyncMock(side_effect=RuntimeError("github down")),
    ):
        assert await github_team.resolve_team_contacts("stripe", ["x"], "Stripe") == []
    # no org / no keywords -> empty without calling anything
    assert await github_team.resolve_team_contacts("", ["x"], "Stripe") == []
    assert await github_team.resolve_team_contacts("stripe", [], "Stripe") == []


async def test_resolve_github_org_uses_hint_then_validates():
    # cached identity hint short-circuits
    org = await github_team.resolve_github_org("Stripe", {"github": "stripe"})
    assert org == "stripe"

    # no hint -> guess + validate via API (cache miss)
    with (
        patch.object(github_team.search_cache_client, "get_json", new=AsyncMock(return_value=None)),
        patch.object(github_team.search_cache_client, "set_json", new=AsyncMock()),
        patch.object(github_team.github_client, "get_org", new=AsyncMock(return_value={"login": "stripe"})),
    ):
        org = await github_team.resolve_github_org("Stripe", None)
    assert org == "stripe"

    # guess does not exist -> None
    with (
        patch.object(github_team.search_cache_client, "get_json", new=AsyncMock(return_value=None)),
        patch.object(github_team.search_cache_client, "set_json", new=AsyncMock()),
        patch.object(github_team.github_client, "get_org", new=AsyncMock(return_value=None)),
    ):
        org = await github_team.resolve_github_org("Some Obscure LLC", None)
    assert org is None


def test_team_confirmed_hm_ranks_first():
    """A GitHub-team-confirmed manager outranks generic same-title EMs."""
    from app.services.people.candidates import _prepare_candidates
    from app.utils.job_context import JobContext

    ctx = JobContext(department="engineering", team_keywords=["mobile", "payments"],
                     manager_titles=["Engineering Manager"], seniority="mid")
    confirmed = {
        "full_name": "Team Lead", "title": "Engineering Manager", "source": "github_team",
        "snippet": "team leader at Acme", "_github_team_member": True,
        "_employment_status": "current",
        "profile_data": {"company_match_confidence": "strong_signal", "github_team": True},
    }
    generic = [
        {"full_name": f"Generic EM {i}", "title": "Engineering Manager", "source": "brave_search",
         "snippet": "Engineering Manager at Acme", "_employment_status": "current",
         "profile_data": {"company_match_confidence": "strong_signal"}}
        for i in range(3)
    ]
    ranked = _prepare_candidates(
        generic[:2] + [confirmed] + generic[2:], company_name="Acme",
        public_identity_slugs=["acme"], bucket="hiring_managers", context=ctx, limit=5,
    )
    assert ranked[0]["full_name"] == "Team Lead"
