"""Tests for The Org traversal candidate expansion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.theorg_discovery_service import discover_theorg_candidates
from app.utils.job_context import JobContext

pytestmark = pytest.mark.asyncio


def _page(url: str, page_props: dict) -> dict:
    return {
        "url": url,
        "next_data": {"props": {"pageProps": page_props}},
        "public_identity_hints": {},
    }


async def test_discover_theorg_candidates_harvests_recruiters_managers_and_peers():
    company = SimpleNamespace(
        name="Zip",
        public_identity_slugs=["zip", "ziphq"],
        identity_hints={},
    )
    context = JobContext(
        department="engineering",
        team_keywords=[],
        domain_keywords=[],
        seniority="junior",
        early_career=True,
    )

    org_page = _page(
        "https://theorg.com/org/ziphq",
        {
            "initialCompany": {"name": "Zip", "slug": "ziphq"},
            "initialTeams": [
                {
                    "slug": "human-resources-and-talent-acquisition",
                    "name": "Human Resources and Talent Acquisition",
                    "description": "Talent team",
                    "memberCount": 6,
                },
                {
                    "slug": "software-development-and-engineering",
                    "name": "Software Development and Engineering",
                    "description": "Engineering team",
                    "memberCount": 59,
                },
            ],
            "initialNodes": [],
        },
    )
    recruiter_team_page = _page(
        "https://theorg.com/org/ziphq/teams/human-resources-and-talent-acquisition",
        {
            "initialCompany": {"name": "Zip", "slug": "ziphq"},
            "initialTeam": {
                "slug": "human-resources-and-talent-acquisition",
                "name": "Human Resources and Talent Acquisition",
                "members": [
                    {"slug": "andre-nguyen", "fullName": "Andre Nguyen", "role": "Senior Technical Recruiter"},
                    {"slug": "tracy-stetz", "fullName": "Tracy Stetz", "role": "Talent Acquisition Partner"},
                ],
            },
        },
    )
    engineering_team_page = _page(
        "https://theorg.com/org/ziphq/teams/software-development-and-engineering",
        {
            "initialCompany": {"name": "Zip", "slug": "ziphq"},
            "initialTeam": {
                "slug": "software-development-and-engineering",
                "name": "Software Development and Engineering",
                "members": [
                    {"slug": "alicia-zhou", "fullName": "Alicia Zhou", "role": "Engineering Manager"},
                    {"slug": "sophia-feng", "fullName": "Sophia Feng", "role": "Software Engineer - Payments"},
                ],
            },
        },
    )
    manager_page = _page(
        "https://theorg.com/org/ziphq/org-chart/alicia-zhou",
        {
            "initialPosition": {
                "slug": "alicia-zhou",
                "fullName": "Alicia Zhou",
                "currentRole": "Engineering Manager",
                "companyV2": {"name": "Zip", "slug": "ziphq"},
                "teams": [
                    {
                        "slug": "software-development-and-engineering",
                        "name": "Software Development and Engineering",
                    }
                ],
                "reports": [
                    {"positionSlug": "nick-galloway", "fullName": "Nick Galloway", "role": "Software Engineer"}
                ],
            }
        },
    )

    async def _fetch(url: str, *, timeout_seconds: int):
        mapping = {
            "https://theorg.com/org/ziphq": org_page,
            "https://theorg.com/org/ziphq/teams/human-resources-and-talent-acquisition": recruiter_team_page,
            "https://theorg.com/org/ziphq/teams/software-development-and-engineering": engineering_team_page,
            "https://theorg.com/org/ziphq/org-chart/alicia-zhou": manager_page,
        }
        return mapping.get(url)

    with (
        patch("app.services.theorg_discovery_service.theorg_client.fetch_page", new_callable=AsyncMock) as mock_fetch,
        patch("app.services.theorg_discovery_service.settings") as mock_settings,
    ):
        mock_fetch.side_effect = _fetch
        mock_settings.theorg_traversal_enabled = True
        mock_settings.theorg_cache_ttl_hours = 24
        mock_settings.theorg_max_team_pages = 3
        mock_settings.theorg_max_manager_pages = 3
        mock_settings.theorg_max_harvested_people = 25
        mock_settings.theorg_timeout_seconds = 20

        results = await discover_theorg_candidates(
            company,
            company_name="Zip",
            context=context,
            current_counts={"recruiters": 0, "hiring_managers": 0, "peers": 0},
        )

    assert [person["full_name"] for person in results["recruiters"]] == ["Andre Nguyen", "Tracy Stetz"]
    assert [person["full_name"] for person in results["hiring_managers"]] == ["Alicia Zhou"]
    assert [person["full_name"] for person in results["peers"]] == ["Sophia Feng", "Nick Galloway"]
    assert company.identity_hints["theorg"]["org"]["parsed"]["org_slug"] == "ziphq"


async def test_discover_theorg_candidates_repairs_stale_slug_from_candidate_urls():
    company = SimpleNamespace(
        name="Whatnot",
        public_identity_slugs=["whatnot-inc"],
        identity_hints={},
    )
    context = JobContext(
        department="engineering",
        team_keywords=[],
        domain_keywords=[],
        seniority="junior",
        early_career=True,
    )

    invalid_org_page = {
        "url": "https://theorg.com/org/whatnot-inc",
        "title": "Page Not Found",
        "html": "<html><title>Page Not Found</title></html>",
        "markdown": "Page Not Found",
        "next_data": {"props": {"pageProps": {"bodyColor": "#fff"}}},
        "public_identity_hints": {"company_slug": "whatnot-inc", "page_type": "org"},
    }
    valid_org_page = _page(
        "https://theorg.com/org/whatnot",
        {
            "initialCompany": {"name": "Whatnot", "slug": "whatnot"},
            "initialTeams": [
                {
                    "slug": "recruiting",
                    "name": "Recruiting",
                    "description": "Early careers and recruiting team",
                    "memberCount": 4,
                }
            ],
            "initialNodes": [],
        },
    )
    recruiting_team_page = _page(
        "https://theorg.com/org/whatnot/teams/recruiting",
        {
            "initialCompany": {"name": "Whatnot", "slug": "whatnot"},
            "initialTeam": {
                "slug": "recruiting",
                "name": "Recruiting",
                "members": [
                    {"slug": "kayla", "fullName": "Kayla Chen", "role": "University Recruiter"},
                    {"slug": "morgan", "fullName": "Morgan Lee", "role": "Talent Acquisition Partner"},
                ],
            },
        },
    )

    async def _fetch(url: str, *, timeout_seconds: int):
        mapping = {
            "https://theorg.com/org/whatnot-inc": invalid_org_page,
            "https://theorg.com/org/whatnot": valid_org_page,
            "https://theorg.com/org/whatnot/teams/recruiting": recruiting_team_page,
        }
        return mapping.get(url)

    with (
        patch("app.services.theorg_discovery_service.theorg_client.fetch_page", new_callable=AsyncMock) as mock_fetch,
        patch("app.services.theorg_discovery_service.settings") as mock_settings,
    ):
        mock_fetch.side_effect = _fetch
        mock_settings.theorg_traversal_enabled = True
        mock_settings.theorg_cache_ttl_hours = 24
        mock_settings.theorg_max_team_pages = 3
        mock_settings.theorg_max_manager_pages = 3
        mock_settings.theorg_max_harvested_people = 25
        mock_settings.theorg_timeout_seconds = 20

        results = await discover_theorg_candidates(
            company,
            company_name="Whatnot",
            context=context,
            current_counts={"recruiters": 0, "hiring_managers": 0, "peers": 0},
            slug_candidates=["whatnot"],
        )

    assert [person["full_name"] for person in results["recruiters"]] == ["Kayla Chen", "Morgan Lee"]
    assert company.identity_hints["theorg"]["preferred_org_slug"] == "whatnot"
    assert company.identity_hints["theorg"]["slug_status"]["whatnot-inc"] == "rejected_not_found"
    assert company.identity_hints["theorg"]["slug_status"]["whatnot"] == "validated"


async def test_discover_theorg_candidates_ignores_incompatible_slug_candidates():
    company = SimpleNamespace(
        name="Whatnot",
        public_identity_slugs=["whatnot"],
        identity_hints={},
    )
    context = JobContext(
        department="engineering",
        team_keywords=[],
        domain_keywords=[],
        seniority="junior",
        early_career=True,
    )

    valid_org_page = _page(
        "https://theorg.com/org/whatnot",
        {
            "initialCompany": {"name": "Whatnot", "slug": "whatnot"},
            "initialTeams": [],
            "initialNodes": [],
        },
    )

    async def _fetch(url: str, *, timeout_seconds: int):
        assert url == "https://theorg.com/org/whatnot"
        return valid_org_page

    with (
        patch("app.services.theorg_discovery_service.theorg_client.fetch_page", new_callable=AsyncMock) as mock_fetch,
        patch("app.services.theorg_discovery_service.settings") as mock_settings,
    ):
        mock_fetch.side_effect = _fetch
        mock_settings.theorg_traversal_enabled = True
        mock_settings.theorg_cache_ttl_hours = 24
        mock_settings.theorg_max_team_pages = 3
        mock_settings.theorg_max_manager_pages = 3
        mock_settings.theorg_max_harvested_people = 25
        mock_settings.theorg_timeout_seconds = 20

        await discover_theorg_candidates(
            company,
            company_name="Whatnot",
            context=context,
            current_counts={"recruiters": 0, "hiring_managers": 0, "peers": 0},
            slug_candidates=["medvet-associates-inc"],
        )

    assert mock_fetch.await_count == 1
