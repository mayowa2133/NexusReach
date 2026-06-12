"""Tests for cadence digest auto-drafting of due follow-up actions."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import cadence_digest_service
from app.services.cadence_service import NextAction

pytestmark = pytest.mark.asyncio


def _action(**overrides) -> NextAction:
    defaults = dict(
        kind="awaiting_reply",
        urgency="high",
        reason="No reply in 6 days.",
        suggested_channel="email",
        suggested_goal="follow_up",
        person_id=str(uuid.uuid4()),
        person_name="Jane Recruiter",
        message_id=None,
        job_id=None,
    )
    defaults.update(overrides)
    return NextAction(**defaults)


def _db_without_recent_drafts():
    db = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=scalar_result)
    return db


def _draft_result():
    return {"message": MagicMock(id=uuid.uuid4())}


async def test_auto_draft_fills_message_id_and_marks_meta():
    db = _db_without_recent_drafts()
    action = _action()

    with patch.object(
        cadence_digest_service.message_service,
        "draft_message",
        new=AsyncMock(return_value=_draft_result()),
    ) as mock_draft:
        drafted = await cadence_digest_service.auto_draft_due_actions(
            db, uuid.uuid4(), [action]
        )

    assert drafted == 1
    assert action.message_id is not None
    assert action.meta.get("auto_drafted") is True
    assert mock_draft.await_args.kwargs["channel"] == "email"
    assert mock_draft.await_args.kwargs["goal"] == "follow_up"


async def test_auto_draft_caps_at_limit():
    db = _db_without_recent_drafts()
    actions = [_action() for _ in range(6)]

    with patch.object(
        cadence_digest_service.message_service,
        "draft_message",
        new=AsyncMock(return_value=_draft_result()),
    ) as mock_draft:
        drafted = await cadence_digest_service.auto_draft_due_actions(
            db, uuid.uuid4(), actions
        )

    assert drafted == cadence_digest_service.MAX_AUTO_DRAFTS_PER_DIGEST
    assert mock_draft.await_count == cadence_digest_service.MAX_AUTO_DRAFTS_PER_DIGEST


async def test_auto_draft_skips_ineligible_actions():
    db = _db_without_recent_drafts()
    actions = [
        _action(kind="draft_unsent"),               # already has a draft flow
        _action(kind="live_targets_unused"),        # not a follow-up kind
        _action(person_id=None),                    # nobody to draft for
        _action(message_id=str(uuid.uuid4())),      # already linked to a draft
        _action(suggested_goal=None),               # no goal to draft with
    ]

    with patch.object(
        cadence_digest_service.message_service,
        "draft_message",
        new=AsyncMock(return_value=_draft_result()),
    ) as mock_draft:
        drafted = await cadence_digest_service.auto_draft_due_actions(
            db, uuid.uuid4(), actions
        )

    assert drafted == 0
    mock_draft.assert_not_awaited()


async def test_auto_draft_skips_person_with_recent_draft():
    db = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = uuid.uuid4()  # existing draft
    db.execute = AsyncMock(return_value=scalar_result)
    action = _action()

    with patch.object(
        cadence_digest_service.message_service,
        "draft_message",
        new=AsyncMock(return_value=_draft_result()),
    ) as mock_draft:
        drafted = await cadence_digest_service.auto_draft_due_actions(
            db, uuid.uuid4(), [action]
        )

    assert drafted == 0
    assert action.message_id is None
    mock_draft.assert_not_awaited()


async def test_auto_draft_tolerates_per_action_failures():
    db = _db_without_recent_drafts()
    first = _action()
    second = _action()

    with patch.object(
        cadence_digest_service.message_service,
        "draft_message",
        new=AsyncMock(side_effect=[RuntimeError("llm down"), _draft_result()]),
    ):
        drafted = await cadence_digest_service.auto_draft_due_actions(
            db, uuid.uuid4(), [first, second]
        )

    assert drafted == 1
    assert first.message_id is None
    assert second.message_id is not None
