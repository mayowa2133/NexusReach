"""Tests for outreach reconcile Celery task guards."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import ProgrammingError


def _make_session(mock_db):
    class FakeSession:
        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, *args):
            return False

    return FakeSession()


@pytest.mark.asyncio()
async def test_reconcile_all_users_skips_when_outreach_logs_table_missing():
    from app.tasks.outreach_reconcile import _reconcile_all_users

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT DISTINCT outreach_logs.user_id FROM outreach_logs",
        {},
        Exception('relation "outreach_logs" does not exist'),
    )
    mock_db.rollback = AsyncMock()

    with (
        patch(
            "app.tasks.outreach_reconcile.async_session",
            return_value=_make_session(mock_db),
        ),
        patch("app.tasks.outreach_reconcile.logger.warning") as mock_warning,
    ):
        result = await _reconcile_all_users()

    assert result == {
        "users": 0,
        "checked": 0,
        "flipped": 0,
        "errors": 0,
        "reply_checked": 0,
        "replied": 0,
        "reply_errors": 0,
    }
    mock_db.rollback.assert_awaited_once()
    mock_warning.assert_called_once()


@pytest.mark.asyncio()
async def test_reconcile_all_users_reraises_other_programming_errors():
    from app.tasks.outreach_reconcile import _reconcile_all_users

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT DISTINCT outreach_logs.user_id FROM outreach_logs",
        {},
        Exception("some other programming error"),
    )
    mock_db.rollback = AsyncMock()

    with patch(
        "app.tasks.outreach_reconcile.async_session",
        return_value=_make_session(mock_db),
    ):
        with pytest.raises(ProgrammingError):
            await _reconcile_all_users()

    mock_db.rollback.assert_not_awaited()
