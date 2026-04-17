"""Tests for GitHub email extraction client."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients import github_email_client


class TestExtractUsername:
    def test_standard_url(self):
        assert github_email_client._extract_username("https://github.com/johndoe") == "johndoe"

    def test_trailing_slash(self):
        assert github_email_client._extract_username("https://github.com/johndoe/") == "johndoe"

    def test_http_url(self):
        assert github_email_client._extract_username("http://github.com/johndoe") == "johndoe"

    def test_no_protocol(self):
        assert github_email_client._extract_username("github.com/johndoe") == "johndoe"

    def test_empty_string(self):
        assert github_email_client._extract_username("") is None

    def test_none(self):
        assert github_email_client._extract_username(None) is None

    def test_invalid_url(self):
        assert github_email_client._extract_username("https://gitlab.com/johndoe") is None

    def test_no_username(self):
        assert github_email_client._extract_username("https://github.com/") is None


class TestIsNoreply:
    def test_github_noreply(self):
        assert github_email_client._is_noreply("123+user@users.noreply.github.com") is True

    def test_regular_email(self):
        assert github_email_client._is_noreply("john@stripe.com") is False

    def test_noreply_github(self):
        assert github_email_client._is_noreply("noreply@github.com") is True


@pytest.mark.asyncio
class TestGetProfileEmail:
    async def test_returns_public_email(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"email": "john@stripe.com", "login": "johndoe"}

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_profile_email("https://github.com/johndoe")

        assert result == "john@stripe.com"

    async def test_returns_none_when_no_email(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"email": None, "login": "johndoe"}

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_profile_email("https://github.com/johndoe")

        assert result is None

    async def test_filters_noreply_email(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"email": "123+user@users.noreply.github.com"}

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_profile_email("https://github.com/johndoe")

        assert result is None

    async def test_returns_none_on_404(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_profile_email("https://github.com/johndoe")

        assert result is None

    async def test_returns_none_for_invalid_url(self):
        result = await github_email_client.get_profile_email("not-a-github-url")
        assert result is None


@pytest.mark.asyncio
class TestGetCommitEmail:
    async def test_extracts_email_from_push_events(self):
        events = [
            {
                "type": "PushEvent",
                "payload": {
                    "commits": [
                        {"author": {"email": "john@stripe.com"}},
                        {"author": {"email": "john@stripe.com"}},
                    ]
                },
            },
            {
                "type": "WatchEvent",
                "payload": {},
            },
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = events

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_commit_email("https://github.com/johndoe")

        assert result == "john@stripe.com"

    async def test_filters_noreply_from_commits(self):
        events = [
            {
                "type": "PushEvent",
                "payload": {
                    "commits": [
                        {"author": {"email": "123+user@users.noreply.github.com"}},
                        {"author": {"email": "john@real.com"}},
                    ]
                },
            },
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = events

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_commit_email("https://github.com/johndoe")

        assert result == "john@real.com"

    async def test_prefers_company_domain_email(self):
        events = [
            {
                "type": "PushEvent",
                "payload": {
                    "commits": [
                        {"author": {"email": "john@personal.com"}},
                        {"author": {"email": "john@personal.com"}},
                        {"author": {"email": "john@stripe.com"}},
                    ]
                },
            },
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = events

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_commit_email(
                "https://github.com/johndoe", company_domain="stripe.com"
            )

        assert result == "john@stripe.com"

    async def test_returns_none_when_no_push_events(self):
        events = [{"type": "WatchEvent", "payload": {}}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = events

        with patch("app.clients.github_email_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await github_email_client.get_commit_email("https://github.com/johndoe")

        assert result is None
