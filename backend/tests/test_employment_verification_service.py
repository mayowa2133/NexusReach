"""Tests for current-company verification service."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.employment_verification_service import (
    _analyze_linkedin_content,
    _analyze_public_content,
    shortlist_people_for_verification,
    verify_current_company_for_person,
    verify_people_current_company,
)

pytestmark = pytest.mark.asyncio


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _person(name: str, *, linkedin_url: str | None = "https://linkedin.com/in/test") -> SimpleNamespace:
    company = SimpleNamespace(name="Twitch", domain="twitch.tv")
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        full_name=name,
        linkedin_url=linkedin_url,
        company=company,
        profile_data={},
        current_company_verified=None,
        current_company_verification_status=None,
        current_company_verification_source=None,
        current_company_verification_confidence=None,
        current_company_verification_evidence=None,
        current_company_verified_at=None,
    )


def test_analyze_linkedin_content_verifies_current_company():
    result = _analyze_linkedin_content(
        "Headline: Senior Software Engineer at Twitch. Experience: Twitch Present.",
        "Twitch",
    )

    assert result.current_company_verified is True
    assert result.current_company_verification_status == "verified"
    assert result.current_company_verification_source == "crawl4ai_linkedin"


def test_analyze_linkedin_content_marks_unclear_result_unverified():
    result = _analyze_linkedin_content(
        "Built ML systems for Twitch and Amazon over the years.",
        "Twitch",
    )

    assert result.current_company_verified is False
    assert result.current_company_verification_status == "unverified"


def test_analyze_public_content_verifies_strong_current_signal():
    result = _analyze_public_content(
        "Currently serving as an Engineering Manager at Twitch since 2022.",
        "Twitch",
    )

    assert result.current_company_verified is True
    assert result.current_company_verification_source == "firecrawl_public_web"


def test_ambiguous_company_variant_does_not_verify_target_company():
    result = _analyze_linkedin_content(
        "Headline: Engineering Manager at Zip Co Limited. Experience: Zip Co Limited Present.",
        "Zip",
    )

    assert result.current_company_verified is False
    assert result.current_company_verification_status == "unverified"
    assert "conflicting company variant" in (result.current_company_verification_evidence or "").lower()


def test_shortlist_people_for_verification_limits_to_top_candidates():
    bucketed = {
        "recruiters": [_person("Recruiter 1"), _person("Recruiter 2"), _person("Recruiter 3")],
        "hiring_managers": [_person("Manager 1"), _person("Manager 2"), _person("Manager 3")],
        "peers": [_person("Peer 1"), _person("Peer 2"), _person("Peer 3"), _person("Peer 4")],
    }

    results = shortlist_people_for_verification(bucketed, max_candidates=5)

    assert [person.full_name for person in results] == [
        "Recruiter 1",
        "Recruiter 2",
        "Manager 1",
        "Manager 2",
        "Peer 1",
    ]


async def test_verify_people_current_company_reorders_verified_people_first():
    recruiter = _person("Recruiter")
    manager = _person("Manager")
    peer_one = _person("Peer 1")
    peer_two = _person("Peer 2")
    bucketed = {
        "recruiters": [recruiter],
        "hiring_managers": [manager],
        "peers": [peer_one, peer_two],
    }

    with patch(
        "app.services.employment_verification_service._verify_person",
        new_callable=AsyncMock,
    ) as mock_verify:
        mock_verify.side_effect = [
            SimpleNamespace(
                current_company_verified=False,
                current_company_verification_status="unverified",
                current_company_verification_source="crawl4ai_linkedin",
                current_company_verification_confidence=30,
                current_company_verification_evidence=None,
                current_company_verified_at=None,
                debug=None,
            ),
            SimpleNamespace(
                current_company_verified=True,
                current_company_verification_status="verified",
                current_company_verification_source="crawl4ai_linkedin",
                current_company_verification_confidence=95,
                current_company_verification_evidence="Works at Twitch currently.",
                current_company_verified_at=None,
                debug=None,
            ),
            SimpleNamespace(
                current_company_verified=False,
                current_company_verification_status="unverified",
                current_company_verification_source="crawl4ai_linkedin",
                current_company_verification_confidence=20,
                current_company_verification_evidence=None,
                current_company_verified_at=None,
                debug=None,
            ),
            SimpleNamespace(
                current_company_verified=True,
                current_company_verification_status="verified",
                current_company_verification_source="crawl4ai_linkedin",
                current_company_verification_confidence=90,
                current_company_verification_evidence="Currently at Twitch.",
                current_company_verified_at=None,
                debug=None,
            ),
        ]
        await verify_people_current_company(
            bucketed,
            company_name="Twitch",
            company_domain="twitch.tv",
        )

    assert bucketed["hiring_managers"][0].current_company_verified is True
    assert bucketed["recruiters"][0].current_company_verification_status == "unverified"
    assert [person.full_name for person in bucketed["peers"]] == ["Peer 2", "Peer 1"]


async def test_verify_current_company_for_person_refreshes_person():
    person = _person("Taylor Example")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(person))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with patch(
        "app.services.employment_verification_service._verify_person",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(
            current_company_verified=True,
            current_company_verification_status="verified",
            current_company_verification_source="crawl4ai_linkedin",
            current_company_verification_confidence=94,
            current_company_verification_evidence="Currently at Twitch.",
            current_company_verified_at=None,
            debug=None,
        ),
    ):
        refreshed = await verify_current_company_for_person(db, person.user_id, person.id)

    assert refreshed.current_company_verified is True
    db.commit.assert_awaited_once()
