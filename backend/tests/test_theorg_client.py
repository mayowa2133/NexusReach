"""Tests for The Org page parsing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.clients.theorg_client import fetch_page, parse_org_page, parse_person_page, parse_team_page


def _page(url: str, page_props: dict) -> dict:
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": page_props}})
        + "</script>"
    )
    return {
        "url": url,
        "html": html,
        "next_data": {"props": {"pageProps": page_props}},
        "public_identity_hints": {},
    }


def test_parse_org_page_extracts_team_refs():
    parsed = parse_org_page(
        _page(
            "https://theorg.com/org/ziphq",
            {
                "initialCompany": {"name": "Zip", "slug": "ziphq"},
                "initialTeams": [
                    {
                        "slug": "software-development-and-engineering",
                        "name": "Software Development and Engineering",
                        "description": "Engineering team",
                        "memberCount": 59,
                    },
                    {
                        "slug": "human-resources-and-talent-acquisition",
                        "name": "Human Resources and Talent Acquisition",
                        "description": "Talent team",
                        "memberCount": 6,
                    },
                ],
                "initialNodes": [],
            },
        )
    )

    assert parsed is not None
    assert parsed["org_slug"] == "ziphq"
    assert [team["slug"] for team in parsed["teams"]] == [
        "software-development-and-engineering",
        "human-resources-and-talent-acquisition",
    ]


def test_parse_team_page_extracts_people_with_person_urls():
    parsed = parse_team_page(
        _page(
            "https://theorg.com/org/ziphq/teams/software-development-and-engineering",
            {
                "initialCompany": {"name": "Zip", "slug": "ziphq"},
                "initialTeam": {
                    "slug": "software-development-and-engineering",
                    "name": "Software Development and Engineering",
                    "members": [
                        {
                            "slug": "alicia-zhou",
                            "fullName": "Alicia Zhou",
                            "role": "Engineering Manager",
                        },
                        {
                            "slug": "sophia-feng",
                            "fullName": "Sophia Feng",
                            "role": "Software Engineer - Payments",
                        },
                    ],
                },
            },
        )
    )

    assert parsed is not None
    assert parsed["team_slug"] == "software-development-and-engineering"
    assert parsed["people"][0]["profile_data"]["public_url"] == "https://theorg.com/org/ziphq/org-chart/alicia-zhou"
    assert parsed["people"][1]["profile_data"]["theorg_team_name"] == "Software Development and Engineering"


def test_parse_person_page_extracts_direct_reports():
    parsed = parse_person_page(
        _page(
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
                        {
                            "positionSlug": "nick-galloway",
                            "fullName": "Nick Galloway",
                            "role": "Software Engineer",
                        }
                    ],
                }
            },
        )
    )

    assert parsed is not None
    assert parsed["person"]["full_name"] == "Alicia Zhou"
    assert parsed["reports"][0]["full_name"] == "Nick Galloway"
    assert parsed["reports"][0]["profile_data"]["theorg_relationship"] == "direct_report"
    assert parsed["reports"][0]["profile_data"]["theorg_parent_name"] == "Alicia Zhou"


@pytest.mark.asyncio
async def test_fetch_page_parses_next_data_from_direct_fetch_without_firecrawl():
    html = _page(
        "https://theorg.com/org/ziphq",
        {
            "initialCompany": {"name": "Zip", "slug": "ziphq"},
            "initialTeams": [],
            "initialNodes": [],
        },
    )["html"]

    with patch(
        "app.clients.theorg_client.public_page_client.fetch_page",
        new_callable=AsyncMock,
        return_value={
            "url": "https://theorg.com/org/ziphq",
            "title": "Zip",
            "html": html,
            "markdown": "",
            "content": "Zip org chart",
            "retrieval_method": "direct",
            "fallback_used": False,
        },
    ):
        page = await fetch_page("https://theorg.com/org/ziphq", timeout_seconds=10)

    assert page is not None
    assert page["next_data"]["props"]["pageProps"]["initialCompany"]["slug"] == "ziphq"
    assert page["retrieval_method"] == "direct"
