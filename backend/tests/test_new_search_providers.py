"""Tests for the added datacenter-safe search providers (You.com, Exa) and the
LinkedIn-restricted Google CSE routing."""

from unittest.mock import AsyncMock, patch

import pytest

from app.clients import exa_search_client, google_search_client, youcom_search_client
from app.config import settings


class TestYoucomClient:
    @pytest.mark.asyncio
    async def test_no_key_is_a_noop(self):
        with patch.object(settings, "youcom_api_key", ""):
            assert await youcom_search_client.search_people("Stripe", titles=["recruiter"]) == []
            assert await youcom_search_client.search_exact_linkedin_profile("Jane Doe", "Stripe") == []

    def test_parses_linkedin_hit(self):
        hit = {
            "url": "https://www.linkedin.com/in/janedoe?trk=x",
            "title": "Jane Doe - Recruiter at Stripe | LinkedIn",
            "snippets": ["Stripe recruiter based in San Francisco"],
        }
        person = youcom_search_client._parse_linkedin_hit(hit, "Stripe")
        assert person["linkedin_url"] == "https://www.linkedin.com/in/janedoe"
        assert person["full_name"] == "Jane Doe"
        assert person["source"] == "youcom"

    def test_skips_non_profile_url(self):
        assert youcom_search_client._parse_linkedin_hit(
            {"url": "https://www.linkedin.com/company/stripe", "title": "Stripe | LinkedIn"}, "Stripe"
        ) is None

    @pytest.mark.asyncio
    async def test_search_people_parses_and_dedupes(self):
        hits = [
            {"url": "https://www.linkedin.com/in/janedoe", "title": "Jane Doe - Recruiter at Stripe | LinkedIn", "snippets": ["x"]},
            {"url": "https://www.linkedin.com/in/janedoe", "title": "Jane Doe - Recruiter at Stripe | LinkedIn", "snippets": ["x"]},
        ]
        with patch.object(settings, "youcom_api_key", "k"), patch.object(
            youcom_search_client, "_run_youcom_query", new=AsyncMock(return_value=hits)
        ):
            results = await youcom_search_client.search_people("Stripe", titles=["recruiter"])
        assert len(results) == 1
        assert results[0]["source"] == "youcom"


class TestExaClient:
    @pytest.mark.asyncio
    async def test_no_key_is_a_noop(self):
        with patch.object(settings, "exa_api_key", ""):
            assert await exa_search_client.search_people("Stripe", titles=["engineer"]) == []

    def test_parses_result_with_name_title(self):
        item = {"url": "https://linkedin.com/in/johnsmith", "title": "John Smith - Engineer at Stripe", "text": "..."}
        person = exa_search_client._parse_exa_result(item, "Stripe")
        assert person["linkedin_url"] == "https://linkedin.com/in/johnsmith"
        assert person["full_name"] == "John Smith"
        assert person["source"] == "exa"

    def test_parses_result_with_name_only_title(self):
        item = {"url": "https://linkedin.com/in/johnsmith", "title": "John Smith | LinkedIn", "text": "..."}
        person = exa_search_client._parse_exa_result(item, "Stripe")
        assert person["full_name"] == "John Smith"

    @pytest.mark.asyncio
    async def test_search_people_parses_mocked_results(self):
        items = [{"url": "https://linkedin.com/in/johnsmith", "title": "John Smith - Engineer at Stripe", "text": "x"}]
        with patch.object(settings, "exa_api_key", "k"), patch.object(
            exa_search_client, "_run_exa_people", new=AsyncMock(return_value=items)
        ):
            results = await exa_search_client.search_people("Stripe", titles=["engineer"])
        assert len(results) == 1
        assert results[0]["source"] == "exa"


class TestLinkedinCseRouting:
    def test_prefers_dedicated_linkedin_cse(self):
        with patch.object(settings, "google_linkedin_cse_id", "li-cse"), patch.object(
            settings, "google_cse_id", "general-cse"
        ):
            assert google_search_client._linkedin_cse_id() == "li-cse"

    def test_falls_back_to_general_cse(self):
        with patch.object(settings, "google_linkedin_cse_id", ""), patch.object(
            settings, "google_cse_id", "general-cse"
        ):
            assert google_search_client._linkedin_cse_id() == "general-cse"


def test_router_registers_youcom_and_exa():
    import inspect

    from app.clients import search_router_client

    src = inspect.getsource(search_router_client.search_people)
    assert '"youcom"' in src and '"exa"' in src
