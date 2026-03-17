"""Tests for email pattern guesser + SMTP verification client."""

import asyncio

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients import email_pattern_client
from app.clients.email_pattern_client import (
    generate_candidates,
    _normalize,
    _resolve_mx,
    _check_smtp,
    _is_catch_all,
    find_email_by_pattern,
)

pytestmark = pytest.mark.asyncio


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("John") == "john"

    def test_strip_accents(self):
        assert _normalize("José") == "jose"

    def test_strip_accents_complex(self):
        assert _normalize("Müller") == "muller"

    def test_remove_non_alpha(self):
        assert _normalize("O'Brien") == "obrien"

    def test_hyphenated_name(self):
        assert _normalize("Mary-Jane") == "maryjane"

    def test_empty_string(self):
        assert _normalize("") == ""


class TestGenerateCandidates:
    def test_standard_names(self):
        result = generate_candidates("John", "Doe", "stripe.com")
        assert result[0] == "john.doe@stripe.com"
        assert result[1] == "jdoe@stripe.com"
        assert result[2] == "johnd@stripe.com"
        assert result[3] == "john@stripe.com"
        assert result[4] == "doe@stripe.com"
        assert result[5] == "john_doe@stripe.com"
        assert result[6] == "john-doe@stripe.com"
        assert result[7] == "doej@stripe.com"
        assert len(result) == 8

    def test_accented_names(self):
        result = generate_candidates("José", "García", "example.com")
        assert result[0] == "jose.garcia@example.com"
        assert result[1] == "jgarcia@example.com"

    def test_empty_first_name(self):
        result = generate_candidates("", "Doe", "stripe.com")
        assert result == []

    def test_empty_last_name(self):
        result = generate_candidates("John", "", "stripe.com")
        assert result == []

    def test_empty_domain(self):
        result = generate_candidates("John", "Doe", "")
        assert result == []

    def test_domain_normalized(self):
        result = generate_candidates("John", "Doe", "  STRIPE.COM  ")
        assert result[0] == "john.doe@stripe.com"

    def test_single_char_names(self):
        result = generate_candidates("A", "B", "x.com")
        assert result[0] == "a.b@x.com"
        assert result[1] == "ab@x.com"
        assert result[3] == "a@x.com"


class TestResolveMx:
    async def test_returns_highest_priority(self):
        mock_record_1 = MagicMock()
        mock_record_1.priority = 10
        mock_record_1.host = "mx1.example.com"

        mock_record_2 = MagicMock()
        mock_record_2.priority = 5
        mock_record_2.host = "mx2.example.com"

        with patch("app.clients.email_pattern_client.aiodns.DNSResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.query = AsyncMock(return_value=[mock_record_1, mock_record_2])
            mock_resolver_cls.return_value = mock_resolver

            result = await _resolve_mx("example.com")

        assert result == "mx2.example.com"

    async def test_returns_none_on_empty(self):
        with patch("app.clients.email_pattern_client.aiodns.DNSResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.query = AsyncMock(return_value=[])
            mock_resolver_cls.return_value = mock_resolver

            result = await _resolve_mx("example.com")

        assert result is None

    async def test_returns_none_on_dns_error(self):
        import aiodns

        with patch("app.clients.email_pattern_client.aiodns.DNSResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.query = AsyncMock(side_effect=aiodns.error.DNSError())
            mock_resolver_cls.return_value = mock_resolver

            result = await _resolve_mx("nonexistent.invalid")

        assert result is None


class TestCheckSmtp:
    async def test_returns_true_on_250(self):
        """SMTP server accepts the recipient → True."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.write = MagicMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        # Simulate SMTP conversation: greeting, HELO, MAIL FROM, RCPT TO, QUIT
        reader.readline = AsyncMock(side_effect=[
            b"220 mx.example.com ESMTP\r\n",
            b"250 Hello\r\n",
            b"250 OK\r\n",
            b"250 OK\r\n",  # RCPT TO accepted
            b"221 Bye\r\n",
        ])

        with patch("app.clients.email_pattern_client.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (reader, writer)
            result = await _check_smtp("john@example.com", "mx.example.com")

        assert result is True

    async def test_returns_false_on_550(self):
        """SMTP server rejects the recipient → False."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.write = MagicMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        reader.readline = AsyncMock(side_effect=[
            b"220 mx.example.com ESMTP\r\n",
            b"250 Hello\r\n",
            b"250 OK\r\n",
            b"550 User not found\r\n",  # RCPT TO rejected
            b"221 Bye\r\n",
        ])

        with patch("app.clients.email_pattern_client.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (reader, writer)
            result = await _check_smtp("nobody@example.com", "mx.example.com")

        assert result is False

    async def test_returns_none_on_4xx(self):
        """SMTP greylisting (4xx) → None (inconclusive)."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.write = MagicMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        reader.readline = AsyncMock(side_effect=[
            b"220 mx.example.com ESMTP\r\n",
            b"250 Hello\r\n",
            b"250 OK\r\n",
            b"450 Try again later\r\n",
            b"221 Bye\r\n",
        ])

        with patch("app.clients.email_pattern_client.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (reader, writer)
            result = await _check_smtp("john@example.com", "mx.example.com")

        assert result is None

    async def test_returns_none_on_connection_timeout(self):
        """Connection timeout → None."""
        with patch("app.clients.email_pattern_client.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = asyncio.TimeoutError()
            result = await _check_smtp("john@example.com", "mx.example.com")

        assert result is None

    async def test_returns_none_on_connection_refused(self):
        """Connection refused → None."""
        with patch("app.clients.email_pattern_client.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError()
            result = await _check_smtp("john@example.com", "mx.example.com")

        assert result is None

    async def test_returns_none_on_bad_greeting(self):
        """Non-220 greeting → None."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.write = MagicMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        reader.readline = AsyncMock(return_value=b"421 Service not available\r\n")

        with patch("app.clients.email_pattern_client.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (reader, writer)
            result = await _check_smtp("john@example.com", "mx.example.com")

        assert result is None


class TestIsCatchAll:
    async def test_catch_all_detected(self):
        """Server accepts random address → catch-all."""
        with patch.object(email_pattern_client, "_check_smtp", new_callable=AsyncMock) as mock_smtp:
            mock_smtp.return_value = True
            result = await _is_catch_all("example.com", "mx.example.com")

        assert result is True
        # Verify a random probe address was used
        call_email = mock_smtp.call_args[0][0]
        assert call_email.startswith("nexusreach-probe-")
        assert call_email.endswith("@example.com")

    async def test_not_catch_all(self):
        """Server rejects random address → not catch-all."""
        with patch.object(email_pattern_client, "_check_smtp", new_callable=AsyncMock) as mock_smtp:
            mock_smtp.return_value = False
            result = await _is_catch_all("example.com", "mx.example.com")

        assert result is False

    async def test_inconclusive_treated_as_not_catch_all(self):
        """SMTP returns None (inconclusive) → not catch-all."""
        with patch.object(email_pattern_client, "_check_smtp", new_callable=AsyncMock) as mock_smtp:
            mock_smtp.return_value = None
            result = await _is_catch_all("example.com", "mx.example.com")

        assert result is False


class TestFindEmailByPattern:
    async def test_returns_first_verified_candidate(self):
        with patch.object(email_pattern_client, "_resolve_mx", new_callable=AsyncMock) as mock_mx, \
             patch.object(email_pattern_client, "_is_catch_all", new_callable=AsyncMock) as mock_catch, \
             patch.object(email_pattern_client, "_check_smtp", new_callable=AsyncMock) as mock_smtp:
            mock_mx.return_value = "mx.stripe.com"
            mock_catch.return_value = False
            # Reject first candidate, accept second
            mock_smtp.side_effect = [False, True]

            result = await find_email_by_pattern("John", "Doe", "stripe.com")

        assert result is not None
        assert result["email"] == "jdoe@stripe.com"
        assert result["source"] == "pattern_smtp"
        assert result["verified"] is True

    async def test_returns_no_mx_status_when_no_mx(self):
        with patch.object(email_pattern_client, "_resolve_mx", new_callable=AsyncMock) as mock_mx:
            mock_mx.return_value = None

            result = await find_email_by_pattern("John", "Doe", "stripe.com")

        assert result["email"] is None
        assert result["domain_status"] == "no_mx"

    async def test_returns_catch_all_status(self):
        with patch.object(email_pattern_client, "_resolve_mx", new_callable=AsyncMock) as mock_mx, \
             patch.object(email_pattern_client, "_is_catch_all", new_callable=AsyncMock) as mock_catch:
            mock_mx.return_value = "mx.stripe.com"
            mock_catch.return_value = True

            result = await find_email_by_pattern("John", "Doe", "stripe.com")

        assert result["email"] is None
        assert result["domain_status"] == "catch_all"

    async def test_returns_all_rejected_status(self):
        with patch.object(email_pattern_client, "_resolve_mx", new_callable=AsyncMock) as mock_mx, \
             patch.object(email_pattern_client, "_is_catch_all", new_callable=AsyncMock) as mock_catch, \
             patch.object(email_pattern_client, "_check_smtp", new_callable=AsyncMock) as mock_smtp:
            mock_mx.return_value = "mx.stripe.com"
            mock_catch.return_value = False
            mock_smtp.return_value = False  # All candidates rejected

            result = await find_email_by_pattern("John", "Doe", "stripe.com")

        assert result["email"] is None
        assert result["domain_status"] == "all_rejected"

    async def test_returns_no_mx_on_empty_inputs(self):
        r1 = await find_email_by_pattern("", "Doe", "stripe.com")
        r2 = await find_email_by_pattern("John", "", "stripe.com")
        r3 = await find_email_by_pattern("John", "Doe", "")
        assert r1["email"] is None
        assert r2["email"] is None
        assert r3["email"] is None

    async def test_timeout_returns_timeout_status(self):
        """30-second total timeout returns timeout domain_status gracefully."""
        async def slow_inner(*args, **kwargs):
            await asyncio.sleep(100)
            return {"email": None, "domain_status": "no_mx"}

        with patch.object(email_pattern_client, "_resolve_mx", new_callable=AsyncMock) as mock_mx, \
             patch.object(email_pattern_client, "_is_catch_all", new_callable=AsyncMock) as mock_catch, \
             patch.object(email_pattern_client, "_check_smtp", side_effect=slow_inner):
            mock_mx.return_value = "mx.stripe.com"
            mock_catch.return_value = False

            # Temporarily reduce timeout for test speed
            original_timeout = email_pattern_client.TOTAL_TIMEOUT_SECONDS
            email_pattern_client.TOTAL_TIMEOUT_SECONDS = 0.1
            try:
                result = await find_email_by_pattern("John", "Doe", "stripe.com")
            finally:
                email_pattern_client.TOTAL_TIMEOUT_SECONDS = original_timeout

        assert result["email"] is None
        assert result["domain_status"] == "timeout"
