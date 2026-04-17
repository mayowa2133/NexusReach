"""Tests for the free hiring-manager email lookup service."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.email_lookup_service import (
    lookup_email,
    parse_linkedin_url,
    resolve_company_domain,
)


class TestParseLinkedInUrl:
    def test_basic_slug(self):
        assert parse_linkedin_url("https://www.linkedin.com/in/john-doe") == ("John", "Doe")

    def test_slug_with_trailing_hash(self):
        assert parse_linkedin_url("https://linkedin.com/in/jane-smith-1a2b3c4d") == ("Jane", "Smith")

    def test_multi_word_last(self):
        first, last = parse_linkedin_url("linkedin.com/in/maria-de-la-cruz")
        assert first == "Maria"
        assert "Cruz" in last

    def test_invalid_returns_none(self):
        assert parse_linkedin_url("https://example.com/foo") == (None, None)
        assert parse_linkedin_url("") == (None, None)

    def test_single_token_no_match(self):
        assert parse_linkedin_url("linkedin.com/in/onlyone") == (None, None)


class TestResolveCompanyDomain:
    @pytest.mark.asyncio
    async def test_explicit_domain_passthrough(self):
        db = AsyncMock()
        result = await resolve_company_domain(db, None, "Stripe.com")
        assert result == "stripe.com"

    @pytest.mark.asyncio
    async def test_domain_from_url(self):
        db = AsyncMock()
        result = await resolve_company_domain(db, None, "https://www.stripe.com/about")
        assert result == "stripe.com"

    @pytest.mark.asyncio
    async def test_naive_guess_when_no_company(self):
        db = AsyncMock()
        # company lookup returns no row
        db.execute = AsyncMock(return_value=AsyncMock(scalar_one_or_none=lambda: None))
        result = await resolve_company_domain(db, "Acme Corp", None)
        assert result == "acmecorp.com"


class TestLookupEmail:
    @pytest.mark.asyncio
    async def test_insufficient_input_no_name(self):
        db = AsyncMock()
        result = await lookup_email(db, company_name="Acme")
        assert result["source"] == "insufficient_input"
        assert result["domain_status"] == "missing_name"

    @pytest.mark.asyncio
    async def test_insufficient_input_no_domain(self):
        db = AsyncMock()
        result = await lookup_email(db, first_name="Jane", last_name="Doe")
        assert result["source"] == "insufficient_input"

    @pytest.mark.asyncio
    async def test_smtp_verified_returns_email(self):
        db = AsyncMock()
        with patch(
            "app.services.email_lookup_service.find_email_by_pattern",
            new=AsyncMock(return_value={
                "email": "jane.doe@stripe.com",
                "verified": True,
                "domain_status": "success",
                "source": "pattern_smtp",
            }),
        ):
            result = await lookup_email(
                db,
                first_name="Jane",
                last_name="Doe",
                company_domain="stripe.com",
            )
        assert result["verified"] is True
        assert result["email"] == "jane.doe@stripe.com"
        assert result["source"] == "smtp_verified"

    @pytest.mark.asyncio
    async def test_smtp_blocked_returns_top_3_suggestions(self):
        db = AsyncMock()
        with patch(
            "app.services.email_lookup_service.find_email_by_pattern",
            new=AsyncMock(return_value={
                "email": None,
                "domain_status": "infrastructure_blocked",
            }),
        ):
            result = await lookup_email(
                db,
                first_name="Jane",
                last_name="Doe",
                company_domain="amazon.com",
            )
        assert result["verified"] is False
        assert result["source"] == "pattern_suggestion"
        assert 1 <= len(result["suggestions"]) <= 3
        assert result["known_company"] is True

    @pytest.mark.asyncio
    async def test_linkedin_url_parses_name(self):
        db = AsyncMock()
        with patch(
            "app.services.email_lookup_service.find_email_by_pattern",
            new=AsyncMock(return_value={"email": None, "domain_status": "no_mx"}),
        ):
            result = await lookup_email(
                db,
                linkedin_url="https://linkedin.com/in/john-smith-abc123",
                company_domain="stripe.com",
            )
        assert result["first_name"] == "John"
        assert result["last_name"] == "Smith"
