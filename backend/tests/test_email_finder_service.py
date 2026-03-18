"""Tests for email finder best-effort behavior."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.email_finder_service import find_email_for_person, verify_person_email

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
        patch("app.services.email_finder_service.hunter_client.domain_search", new_callable=AsyncMock, return_value={"pattern": None, "accept_all": None, "emails": []}),
        patch("app.services.email_finder_service.api_usage_service.get_monthly_usage_count", new_callable=AsyncMock, return_value=0),
        patch("app.services.email_finder_service.api_usage_service.has_monthly_usage", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.api_usage_service.record_usage", new_callable=AsyncMock),
        patch("app.services.email_finder_service.settings") as mock_settings,
    ):
        mock_settings.hunter_api_key = ""
        mock_settings.proxycurl_api_key = ""
        mock_settings.hunter_pattern_monthly_budget = 25
        result = await find_email_for_person(mock_db, person.user_id, person.id, mode="best_effort")

    assert result["result_type"] == "best_guess"
    assert result["best_guess_email"] == "alex.lee@affirm.com"
    assert result["guess_basis"] == "generic_pattern"
    assert result["verified"] is False
    assert "pattern_suggestion_low_confidence" in result["failure_reasons"]
    assert "hunter_api_key_missing" in result["failure_reasons"]
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
        patch("app.services.email_finder_service.hunter_client.domain_search", new_callable=AsyncMock, return_value={"pattern": None, "accept_all": None, "emails": []}),
        patch("app.services.email_finder_service.api_usage_service.get_monthly_usage_count", new_callable=AsyncMock, return_value=0),
        patch("app.services.email_finder_service.api_usage_service.has_monthly_usage", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.api_usage_service.record_usage", new_callable=AsyncMock),
        patch("app.services.email_finder_service.settings") as mock_settings,
    ):
        mock_settings.hunter_api_key = ""
        mock_settings.proxycurl_api_key = ""
        mock_settings.hunter_pattern_monthly_budget = 25
        result = await find_email_for_person(mock_db, person.user_id, person.id, mode="verified_only")

    assert result["result_type"] == "not_found"
    assert result["email"] is None
    assert "pattern_suggestion_low_confidence" in result["failure_reasons"]


async def test_hunter_pattern_learning_persists_company_pattern_and_improves_guess(mock_db):
    person = _person()
    mock_db.execute.return_value = _ScalarResult(person)

    with (
        patch("app.services.email_finder_service.is_domain_blocked", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.record_smtp_result", new_callable=AsyncMock),
        patch("app.services.email_finder_service.email_pattern_client.find_email_by_pattern", new_callable=AsyncMock, return_value={"email": None, "domain_status": "catch_all"}),
        patch("app.services.email_finder_service.hunter_client.domain_search", new_callable=AsyncMock, return_value={
            "pattern": "first.last",
            "accept_all": True,
            "emails": [{"email": "jane.doe@affirm.com", "first_name": "Jane", "last_name": "Doe", "confidence": 88}],
        }) as mock_domain_search,
        patch("app.services.email_finder_service.email_suggestion_client.suggest_email", return_value={
            "email": "alex.lee@affirm.com",
            "confidence": 85,
            "suggestions": [{"email": "alex.lee@affirm.com", "confidence": 85}],
        }),
        patch("app.services.email_finder_service.gravatar_client.check_gravatar", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.apollo_client.enrich_person", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.api_usage_service.get_monthly_usage_count", new_callable=AsyncMock, return_value=0),
        patch("app.services.email_finder_service.api_usage_service.has_monthly_usage", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.api_usage_service.record_usage", new_callable=AsyncMock) as mock_record_usage,
        patch("app.services.email_finder_service.settings") as mock_settings,
    ):
        mock_settings.hunter_api_key = "hunter-key"
        mock_settings.proxycurl_api_key = ""
        mock_settings.hunter_pattern_monthly_budget = 25
        result = await find_email_for_person(mock_db, person.user_id, person.id, mode="best_effort")

    assert result["result_type"] == "best_guess"
    assert result["best_guess_email"] == "alex.lee@affirm.com"
    assert result["guess_basis"] == "learned_company_pattern"
    assert "hunter_pattern_learning" in result["tried"]
    assert "hunter_pattern_learned" in result["tried"]
    assert person.company.email_pattern == "first.last"
    assert person.company.email_pattern_confidence == 85
    assert person.work_email == "alex.lee@affirm.com"
    assert person.email_source == "pattern_suggestion_learned"
    mock_domain_search.assert_awaited_once()
    mock_record_usage.assert_awaited_once()
    assert mock_record_usage.await_args.kwargs["credits_used"] == 1.0
    assert mock_record_usage.await_args.kwargs["details"]["operation"] == "domain_search"


async def test_hunter_pattern_learning_respects_monthly_budget(mock_db):
    person = _person()
    mock_db.execute.return_value = _ScalarResult(person)

    with (
        patch("app.services.email_finder_service.is_domain_blocked", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.record_smtp_result", new_callable=AsyncMock),
        patch("app.services.email_finder_service.email_pattern_client.find_email_by_pattern", new_callable=AsyncMock, return_value={"email": None, "domain_status": "catch_all"}),
        patch("app.services.email_finder_service.email_suggestion_client.suggest_email", return_value={
            "email": "alex.lee@affirm.com",
            "confidence": 40,
            "suggestions": [{"email": "alex.lee@affirm.com", "confidence": 40}],
        }),
        patch("app.services.email_finder_service.gravatar_client.check_gravatar", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.apollo_client.enrich_person", new_callable=AsyncMock, return_value=None),
        patch(
            "app.services.email_finder_service.hunter_client.domain_search",
            new_callable=AsyncMock,
            return_value={"pattern": None, "accept_all": None, "emails": []},
        ) as mock_domain_search,
        patch("app.services.email_finder_service.api_usage_service.get_monthly_usage_count", new_callable=AsyncMock, return_value=25),
        patch("app.services.email_finder_service.api_usage_service.has_monthly_usage", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.api_usage_service.record_usage", new_callable=AsyncMock) as mock_record_usage,
        patch("app.services.email_finder_service.settings") as mock_settings,
    ):
        mock_settings.hunter_api_key = "hunter-key"
        mock_settings.proxycurl_api_key = ""
        mock_settings.hunter_pattern_monthly_budget = 25
        result = await find_email_for_person(mock_db, person.user_id, person.id, mode="best_effort")

    assert result["result_type"] == "best_guess"
    assert result["guess_basis"] == "generic_pattern"
    assert "hunter_pattern_budget_exhausted" in result["failure_reasons"]
    assert "hunter_pattern_learning_skipped" in result["tried"]
    mock_domain_search.assert_not_awaited()
    mock_record_usage.assert_not_awaited()


async def test_hunter_pattern_learning_does_not_auto_return_exact_domain_match(mock_db):
    person = _person()
    mock_db.execute.return_value = _ScalarResult(person)

    with (
        patch("app.services.email_finder_service.is_domain_blocked", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.record_smtp_result", new_callable=AsyncMock),
        patch("app.services.email_finder_service.email_pattern_client.find_email_by_pattern", new_callable=AsyncMock, return_value={"email": None, "domain_status": "catch_all"}),
        patch("app.services.email_finder_service.email_suggestion_client.suggest_email", return_value={
            "email": "alex.lee@affirm.com",
            "confidence": 85,
            "suggestions": [{"email": "alex.lee@affirm.com", "confidence": 85}],
        }),
        patch("app.services.email_finder_service.gravatar_client.check_gravatar", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.apollo_client.enrich_person", new_callable=AsyncMock, return_value=None),
        patch("app.services.email_finder_service.hunter_client.domain_search", new_callable=AsyncMock, return_value={
            "pattern": "first.last",
            "accept_all": True,
            "emails": [{"email": "alex.lee@affirm.com", "first_name": "Alex", "last_name": "Lee", "confidence": 91}],
        }),
        patch("app.services.email_finder_service.api_usage_service.get_monthly_usage_count", new_callable=AsyncMock, return_value=0),
        patch("app.services.email_finder_service.api_usage_service.has_monthly_usage", new_callable=AsyncMock, return_value=False),
        patch("app.services.email_finder_service.api_usage_service.record_usage", new_callable=AsyncMock),
        patch("app.services.email_finder_service.settings") as mock_settings,
    ):
        mock_settings.hunter_api_key = "hunter-key"
        mock_settings.proxycurl_api_key = ""
        mock_settings.hunter_pattern_monthly_budget = 25
        result = await find_email_for_person(mock_db, person.user_id, person.id, mode="best_effort")

    assert result["email"] == "alex.lee@affirm.com"
    assert result["source"] == "pattern_suggestion"
    assert result["verified"] is False
    assert result["result_type"] == "best_guess"
    assert person.company.email_pattern == "first.last"
    assert person.company.email_pattern_confidence == 85


async def test_verify_person_email_records_hunter_usage(mock_db):
    person = _person()
    person.work_email = "alex.lee@affirm.com"
    mock_db.execute.return_value = _ScalarResult(person)

    with (
        patch(
            "app.services.email_finder_service.hunter_client.verify_email",
            new_callable=AsyncMock,
            return_value={
                "email": "alex.lee@affirm.com",
                "status": "valid",
                "result": "deliverable",
                "score": 98,
                "disposable": False,
                "webmail": False,
            },
        ),
        patch("app.services.email_finder_service.api_usage_service.record_usage", new_callable=AsyncMock) as mock_record_usage,
    ):
        result = await verify_person_email(mock_db, person.user_id, person.id)

    assert result["status"] == "valid"
    assert person.email_verified is True
    mock_record_usage.assert_awaited_once()
    assert mock_record_usage.await_args.kwargs["credits_used"] == 0.5
    assert mock_record_usage.await_args.kwargs["details"]["operation"] == "email_verifier"
