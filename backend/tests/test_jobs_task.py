"""Tests for job refresh / ATS discovery Celery task guards."""

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
async def test_discover_all_boards_skips_when_search_preferences_table_missing():
    from app.tasks.jobs import _discover_all_boards

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT * FROM search_preferences",
        {},
        Exception('relation "search_preferences" does not exist'),
    )
    mock_db.rollback = AsyncMock()

    with (
        patch("app.tasks.jobs.async_session", return_value=_make_session(mock_db)),
        patch("app.tasks.jobs.logger.warning") as mock_warning,
    ):
        await _discover_all_boards()

    mock_db.rollback.assert_awaited_once()
    mock_warning.assert_called_once()


@pytest.mark.asyncio()
async def test_discover_all_boards_reraises_other_programming_errors():
    from app.tasks.jobs import _discover_all_boards

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT * FROM search_preferences",
        {},
        Exception("some other programming error"),
    )
    mock_db.rollback = AsyncMock()

    with patch("app.tasks.jobs.async_session", return_value=_make_session(mock_db)):
        with pytest.raises(ProgrammingError):
            await _discover_all_boards()

    mock_db.rollback.assert_not_awaited()


@pytest.mark.asyncio()
async def test_refresh_all_skips_when_search_preferences_table_missing():
    from app.tasks.jobs import _refresh_all

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT DISTINCT search_preferences.user_id FROM search_preferences",
        {},
        Exception('relation "search_preferences" does not exist'),
    )
    mock_db.rollback = AsyncMock()

    with (
        patch("app.tasks.jobs.async_session", return_value=_make_session(mock_db)),
        patch("app.tasks.jobs.logger.warning") as mock_warning,
    ):
        await _refresh_all()

    mock_db.rollback.assert_awaited_once()
    mock_warning.assert_called_once()


@pytest.mark.asyncio()
async def test_refresh_all_reraises_other_programming_errors():
    from app.tasks.jobs import _refresh_all

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT DISTINCT search_preferences.user_id FROM search_preferences",
        {},
        Exception("some other programming error"),
    )
    mock_db.rollback = AsyncMock()

    with patch("app.tasks.jobs.async_session", return_value=_make_session(mock_db)):
        with pytest.raises(ProgrammingError):
            await _refresh_all()

    mock_db.rollback.assert_not_awaited()
