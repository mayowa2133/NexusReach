"""Tests for Gravatar existence-check client."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients import gravatar_client

pytestmark = pytest.mark.asyncio


class TestCheckGravatar:
    async def test_returns_true_when_exists(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("app.clients.gravatar_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await gravatar_client.check_gravatar("john@stripe.com")

        assert result is True
        # Verify the request used the correct hash and params
        call_args = mock_client.get.call_args
        assert "gravatar.com/avatar/" in call_args[0][0]
        assert call_args[1]["params"] == {"d": "404", "s": "1"}

    async def test_returns_false_when_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("app.clients.gravatar_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await gravatar_client.check_gravatar("nobody@example.com")

        assert result is False

    async def test_returns_false_on_timeout(self):
        import httpx

        with patch("app.clients.gravatar_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timed out")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await gravatar_client.check_gravatar("john@stripe.com")

        assert result is False

    async def test_returns_false_for_empty_email(self):
        result = await gravatar_client.check_gravatar("")
        assert result is False

    async def test_returns_false_for_invalid_email(self):
        result = await gravatar_client.check_gravatar("not-an-email")
        assert result is False

    async def test_normalizes_email_case(self):
        """Gravatar hash should be computed from lowercased email."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("app.clients.gravatar_client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # Call with uppercase — should still work
            result = await gravatar_client.check_gravatar("JOHN@STRIPE.COM")

        assert result is True
        # The hash should be computed from lowercase
        import hashlib
        expected_hash = hashlib.md5("john@stripe.com".encode()).hexdigest()
        call_url = mock_client.get.call_args[0][0]
        assert expected_hash in call_url
