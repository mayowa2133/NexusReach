"""Tests for email finder best-effort behavior."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email_finder_service import find_email_for_person

pytestmark = pytest.mark.asyncio


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _person() -> SimpleNamespace:
    company = SimpleNamespace(
        domain="affirm.com",
        email_pattern=None,
        email_pattern_confidence=None,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        full_name="Alex Lee",
        github_url=None,
        apollo_id=None,
        linkedin_url="https://linkedin.com/in/alexlee",
        work_email=None,
        email_source=None,
        email_verified=False,
        email_confidence=None,
        profile_data=None,
        company=company,
    )


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


async def test_best_effort_returns_low_confidence_suggestion(mock_db):
    person = _person()
    mock_db.execute.return_value = _ScalarResult(person)

    with (
        patch("app.services.email_finder_service.github_email_client.get_profile_email", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.github_email_client.get_commit_email", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.is_domain_blocked", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.email_pattern_client.find_email_by_pattern", new_callable=AsyncMock, return_value={"email": None, "domain_status": "all_rejected"}),
        patch("app.services.email_finder_service.email_suggestion_client.suggest_email", return_value={
            "email": "alex.lee@affirm.com",
            "confidence": 40,
            "suggestions": [{"email": "alex.lee@affirm.com", "confidence": 40}],
        }),
        patch("app.services.email_finder_service.gravatar_client.check_gravatar", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.apollo_client.enrich_person", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.hunter_client.find_email", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.hunter_client.domain_search", new_callable=AsyncMock, return_value=[]),
        patch("app.services.email_finder_service.settings") as mock_settings,
    ):
        mock_settings.hunter_api_key = ""
        mock_settings.proxycurl_api_key = ""
        result = await find_email_for_person(mock_db, person.user_id, person.id, mode="best_effort")

    assert result["result_type"] == "best_guess"
    assert result["best_guess_email"] == "alex.lee@affirm.com"
    assert result["verified"] is False
    assert "pattern_suggestion_low_confidence" in result["failure_reasons"]
    assert person.work_email is None


async def test_verified_only_suppresses_low_confidence_suggestion(mock_db):
    person = _person()
    mock_db.execute.return_value = _ScalarResult(person)

    with (
        patch("app.services.email_finder_service.github_email_client.get_profile_email", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.github_email_client.get_commit_email", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.is_domain_blocked", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.email_pattern_client.find_email_by_pattern", new_callable=AsyncMock, return_value={"email": None, "domain_status": "all_rejected"}),
        patch("app.services.email_finder_service.email_suggestion_client.suggest_email", return_value={
            "email": "alex.lee@affirm.com",
            "confidence": 40,
            "suggestions": [{"email": "alex.lee@affirm.com", "confidence": 40}],
        }),
        patch("app.services.email_finder_service.gravatar_client.check_gravatar", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.apollo_client.enrich_person", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.hunter_client.find_email", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.hunter_client.domain_search", new_callable=AsyncMock, return_value=[]),
        patch("app.services.email_finder_service.settings") as mock_settings,
    ):
        mock_settings.hunter_api_key = ""
        mock_settings.proxycurl_api_key = ""
        result = await find_email_for_person(mock_db, person.user_id, person.id, mode="verified_only")

    assert result["result_type"] == "not_found"
    assert result["email"] is None
    assert "pattern_suggestion_low_confidence" in result["failure_reasons"]
