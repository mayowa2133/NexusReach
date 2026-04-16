"""Tests for post-send reconciliation of staged drafts."""

from __future__ import annotations

import uuid
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


def _make_log(**overrides):
    log = SimpleNamespace(
        id=overrides.get("id", uuid.uuid4()),
        status=overrides.get("status", "draft"),
        provider=overrides.get("provider", "gmail"),
        provider_message_id=overrides.get("provider_message_id", "msg_123"),
        provider_draft_id=overrides.get("provider_draft_id", "draft_123"),
        sent_at=None,
        last_contacted_at=None,
    )
    return log


async def test_reconcile_flips_log_when_gmail_reports_sent():
    user_id = uuid.uuid4()
    log = _make_log(provider="gmail", provider_message_id="gmail_abc")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult([log]))
    db.commit = AsyncMock()

    with patch.object(
        outreach_reconcile_service.gmail_service,
        "check_draft_sent",
        new=AsyncMock(return_value={"sent": True, "message_id": "gmail_abc", "label_ids": ["SENT"]}),
    ):
        stats = await outreach_reconcile_service.reconcile_sent_drafts(db, user_id)

    assert log.status == "sent"
    assert log.sent_at is not None
    assert log.last_contacted_at == log.sent_at
    assert stats == {"checked": 1, "flipped": 1, "errors": 0}
    db.commit.assert_awaited_once()


async def test_reconcile_leaves_log_alone_when_still_draft():
    user_id = uuid.uuid4()
    log = _make_log(provider="outlook", provider_message_id="out_xyz")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult([log]))
    db.commit = AsyncMock()

    with patch.object(
        outreach_reconcile_service.outlook_service,
        "check_draft_sent",
        new=AsyncMock(return_value={"sent": False, "message_id": "out_xyz", "is_draft": True}),
    ):
        stats = await outreach_reconcile_service.reconcile_sent_drafts(db, user_id)

    assert log.status == "draft"
    assert log.sent_at is None
    assert stats == {"checked": 1, "flipped": 0, "errors": 0}
    db.commit.assert_not_awaited()


async def test_reconcile_counts_errors_without_flipping():
    user_id = uuid.uuid4()
    log = _make_log(provider="gmail")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult([log]))
    db.commit = AsyncMock()

    with patch.object(
        outreach_reconcile_service.gmail_service,
        "check_draft_sent",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        stats = await outreach_reconcile_service.reconcile_sent_drafts(db, user_id)

    assert log.status == "draft"
    assert stats == {"checked": 1, "flipped": 0, "errors": 1}
    db.commit.assert_not_awaited()


async def test_reconcile_skips_logs_without_provider_checker():
    """An unknown provider string should not be polled or error out."""
    user_id = uuid.uuid4()
    log = _make_log(provider="smoke-signal")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult([log]))
    db.commit = AsyncMock()

    stats = await outreach_reconcile_service.reconcile_sent_drafts(db, user_id)

    assert log.status == "draft"
    assert stats == {"checked": 0, "flipped": 0, "errors": 0}
