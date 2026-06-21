"""Tests for auto-prospect Celery tasks."""

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
async def test_process_pending_sends_skips_when_messages_table_missing():
    from app.tasks.auto_prospect import _process_pending_sends

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT DISTINCT messages.user_id FROM messages",
        {},
        Exception('relation "messages" does not exist'),
    )
    mock_db.rollback = AsyncMock()

    with (
        patch("app.tasks.auto_prospect.async_session", return_value=_make_session(mock_db)),
        patch("app.tasks.auto_prospect.logger.warning") as mock_warning,
    ):
        result = await _process_pending_sends()

    assert result == {"sent": 0, "cancelled": 0, "errors": 0}
    mock_db.rollback.assert_awaited_once()
    mock_warning.assert_called_once()


@pytest.mark.asyncio()
async def test_process_pending_sends_reraises_other_programming_errors():
    from app.tasks.auto_prospect import _process_pending_sends

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT DISTINCT messages.user_id FROM messages",
        {},
        Exception("some other programming error"),
    )
    mock_db.rollback = AsyncMock()

    with patch("app.tasks.auto_prospect.async_session", return_value=_make_session(mock_db)):
        with pytest.raises(ProgrammingError):
            await _process_pending_sends()

    mock_db.rollback.assert_not_awaited()
