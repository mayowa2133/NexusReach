"""Tests for reply reconciliation of sent outreach (sent -> responded)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import outreach_reconcile_service

pytestmark = pytest.mark.asyncio


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        value = self._value

        class _Scalars:
            def __init__(self, raw):
                self._raw = raw

            def all(self):
                if isinstance(self._raw, list):
                    return self._raw
                return [] if self._raw is None else [self._raw]

        return _Scalars(value)


def _make_sent_log(**overrides):
    return SimpleNamespace(
        id=overrides.get("id", uuid.uuid4()),
        status=overrides.get("status", "sent"),
        channel=overrides.get("channel", "email"),
        provider=overrides.get("provider", "gmail"),
        provider_message_id=overrides.get("provider_message_id", "msg_123"),
        sent_at=overrides.get(
            "sent_at", datetime.now(timezone.utc) - timedelta(days=2)
        ),
        response_received=overrides.get("response_received", False),
        job_id=overrides.get("job_id", None),
        person=overrides.get(
            "person", SimpleNamespace(full_name="Jane Recruiter")
        ),
    )


def _db_with(logs):
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(logs))
    db.commit = AsyncMock()
    return db


async def test_reply_flips_status_and_notifies():
    user_id = uuid.uuid4()
    log = _make_sent_log(provider="gmail")
    db = _db_with([log])

    with (
        patch.object(
            outreach_reconcile_service.gmail_service,
            "check_reply_received",
            new=AsyncMock(
                return_value={"replied": True, "reply_count": 1, "last_reply_at": None}
            ),
        ) as mock_check,
        patch.object(
            outreach_reconcile_service, "create_notification", new=AsyncMock()
        ) as mock_notify,
        patch.object(
            outreach_reconcile_service, "capture_event"
        ) as mock_capture,
    ):
        stats = await outreach_reconcile_service.reconcile_replies(db, user_id)

    assert stats == {"checked": 1, "replied": 1, "errors": 0}
    assert log.status == "responded"
    assert log.response_received is True
    # checker received the send time as the reply cutoff
    assert mock_check.await_args.kwargs["since"] == log.sent_at
    assert mock_check.await_args.kwargs["provider_message_id"] == "msg_123"
    # notification mentions the contact by name
    assert "Jane Recruiter" in mock_notify.await_args.kwargs["title"]
    assert mock_notify.await_args.kwargs["type"] == "outreach_reply"
    # analytics event fired with provider context
    assert mock_capture.call_args.args[1] == "outreach_reply_received"
    assert mock_capture.call_args.kwargs["properties"]["provider"] == "gmail"
    db.commit.assert_awaited()


async def test_no_reply_leaves_log_untouched():
    user_id = uuid.uuid4()
    log = _make_sent_log(provider="outlook")
    db = _db_with([log])

    with (
        patch.object(
            outreach_reconcile_service.outlook_service,
            "check_reply_received",
            new=AsyncMock(
                return_value={"replied": False, "reply_count": 0, "last_reply_at": None}
            ),
        ),
        patch.object(
            outreach_reconcile_service, "create_notification", new=AsyncMock()
        ) as mock_notify,
    ):
        stats = await outreach_reconcile_service.reconcile_replies(db, user_id)

    assert stats == {"checked": 1, "replied": 0, "errors": 0}
    assert log.status == "sent"
    assert log.response_received is False
    mock_notify.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_checker_error_counts_and_continues():
    user_id = uuid.uuid4()
    failing = _make_sent_log(provider="gmail", provider_message_id="boom")
    ok = _make_sent_log(provider="gmail", provider_message_id="fine")
    db = _db_with([failing, ok])

    async def _check(db_, uid, *, provider_message_id, since):
        if provider_message_id == "boom":
            raise RuntimeError("api down")
        return {"replied": True, "reply_count": 1, "last_reply_at": None}

    with (
        patch.object(
            outreach_reconcile_service.gmail_service,
            "check_reply_received",
            new=AsyncMock(side_effect=_check),
        ),
        patch.object(
            outreach_reconcile_service, "create_notification", new=AsyncMock()
        ),
        patch.object(outreach_reconcile_service, "capture_event"),
    ):
        stats = await outreach_reconcile_service.reconcile_replies(db, user_id)

    assert stats == {"checked": 2, "replied": 1, "errors": 1}
    assert failing.status == "sent"
    assert ok.status == "responded"


async def test_unknown_provider_is_skipped():
    user_id = uuid.uuid4()
    log = _make_sent_log(provider="smtp")
    db = _db_with([log])

    stats = await outreach_reconcile_service.reconcile_replies(db, user_id)

    assert stats == {"checked": 0, "replied": 0, "errors": 0}
    assert log.status == "sent"


async def test_notification_failure_does_not_block_flip():
    user_id = uuid.uuid4()
    log = _make_sent_log(provider="gmail", person=None)
    db = _db_with([log])

    with (
        patch.object(
            outreach_reconcile_service.gmail_service,
            "check_reply_received",
            new=AsyncMock(
                return_value={"replied": True, "reply_count": 2, "last_reply_at": None}
            ),
        ),
        patch.object(
            outreach_reconcile_service,
            "create_notification",
            new=AsyncMock(side_effect=RuntimeError("notify down")),
        ),
        patch.object(outreach_reconcile_service, "capture_event") as mock_capture,
    ):
        stats = await outreach_reconcile_service.reconcile_replies(db, user_id)

    assert stats == {"checked": 1, "replied": 1, "errors": 0}
    assert log.status == "responded"
    assert log.response_received is True
    mock_capture.assert_called_once()
