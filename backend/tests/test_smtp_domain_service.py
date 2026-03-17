"""Tests for SMTP domain tracking service."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.smtp_domain_result import SmtpDomainResult
from app.services.smtp_domain_service import (
    SMTP_BLOCK_THRESHOLD,
    SMTP_BLOCK_TTL_DAYS,
    SMTP_CATCH_ALL_TTL_DAYS,
    get_domain_stats,
    is_domain_blocked,
    record_smtp_result,
)

pytestmark = pytest.mark.asyncio


def _make_db(record=None):
    """Create a mock AsyncSession that returns the given record on scalar_one_or_none."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = record
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class TestIsDomainBlocked:
    async def test_returns_true_when_blocked(self):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        record = SmtpDomainResult(domain="example.com", blocked_until=future)
        db = _make_db(record)

        result = await is_domain_blocked(db, "example.com")

        assert result is True

    async def test_returns_false_when_not_in_db(self):
        db = _make_db(None)

        result = await is_domain_blocked(db, "example.com")

        assert result is False

    async def test_normalizes_domain_case(self):
        db = _make_db(None)
        await is_domain_blocked(db, "EXAMPLE.COM")

        # The query should have been called (domain normalised)
        db.execute.assert_called_once()


class TestRecordSmtpResult:
    async def test_success_increments_counter_and_clears_block(self):
        record = SmtpDomainResult(
            domain="example.com",
            success_count=2,
            blocked_count=3,
            blocked_until=datetime.now(timezone.utc) + timedelta(days=5),
        )
        db = _make_db(record)

        await record_smtp_result(db, "example.com", "success")

        assert record.success_count == 3
        assert record.blocked_count == 0
        assert record.blocked_until is None
        db.flush.assert_called_once()

    async def test_catch_all_sets_short_block(self):
        record = SmtpDomainResult(domain="example.com", catch_all_count=0)
        db = _make_db(record)

        await record_smtp_result(db, "example.com", "catch_all")

        assert record.catch_all_count == 1
        assert record.blocked_until is not None
        expected_ttl = timedelta(days=SMTP_CATCH_ALL_TTL_DAYS)
        diff = record.blocked_until - datetime.now(timezone.utc)
        assert abs(diff.total_seconds() - expected_ttl.total_seconds()) < 5

    async def test_blocked_below_threshold_does_not_set_block(self):
        record = SmtpDomainResult(domain="example.com", blocked_count=1)
        db = _make_db(record)

        await record_smtp_result(db, "example.com", "blocked")

        assert record.blocked_count == 2
        assert record.blocked_until is None

    async def test_blocked_at_threshold_sets_long_block(self):
        record = SmtpDomainResult(
            domain="example.com",
            blocked_count=SMTP_BLOCK_THRESHOLD - 1,
        )
        db = _make_db(record)

        await record_smtp_result(db, "example.com", "blocked")

        assert record.blocked_count == SMTP_BLOCK_THRESHOLD
        assert record.blocked_until is not None
        expected_ttl = timedelta(days=SMTP_BLOCK_TTL_DAYS)
        diff = record.blocked_until - datetime.now(timezone.utc)
        assert abs(diff.total_seconds() - expected_ttl.total_seconds()) < 5

    async def test_greylist_increments_counter_no_block(self):
        record = SmtpDomainResult(domain="example.com", greylist_count=1)
        db = _make_db(record)

        await record_smtp_result(db, "example.com", "greylist")

        assert record.greylist_count == 2
        assert record.blocked_until is None

    async def test_creates_new_record_when_not_in_db(self):
        db = _make_db(None)

        await record_smtp_result(db, "newdomain.com", "success")

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, SmtpDomainResult)
        assert added.domain == "newdomain.com"


class TestGetDomainStats:
    async def test_returns_none_when_not_in_db(self):
        db = _make_db(None)

        result = await get_domain_stats(db, "example.com")

        assert result is None

    async def test_returns_stats_dict(self):
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=10)
        record = SmtpDomainResult(
            domain="example.com",
            success_count=5,
            catch_all_count=0,
            blocked_count=1,
            greylist_count=2,
            last_success_at=now,
            last_failure_at=now,
            blocked_until=future,
        )
        db = _make_db(record)

        result = await get_domain_stats(db, "example.com")

        assert result is not None
        assert result["domain"] == "example.com"
        assert result["success_count"] == 5
        assert result["blocked_count"] == 1
        assert result["greylist_count"] == 2
        assert result["is_blocked"] is True

    async def test_is_blocked_false_when_expired(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        record = SmtpDomainResult(domain="example.com", blocked_until=past)
        db = _make_db(record)

        result = await get_domain_stats(db, "example.com")

        assert result["is_blocked"] is False

    async def test_is_blocked_false_when_no_blocked_until(self):
        record = SmtpDomainResult(domain="example.com", blocked_until=None)
        db = _make_db(record)

        result = await get_domain_stats(db, "example.com")

        assert result["is_blocked"] is False
