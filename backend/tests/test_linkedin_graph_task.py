"""Tests for LinkedIn graph cleanup Celery task guards."""

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
async def test_cleanup_orphaned_sessions_skips_when_sync_runs_table_missing():
    from app.tasks.linkedin_graph import _cleanup_orphaned_sessions

    mock_db = AsyncMock()
    mock_db.rollback = AsyncMock()

    with (
        patch(
            "app.tasks.linkedin_graph.async_session",
            return_value=_make_session(mock_db),
        ),
        patch(
            "app.tasks.linkedin_graph.cleanup_orphaned_sync_sessions",
            new=AsyncMock(
                side_effect=ProgrammingError(
                    "SELECT * FROM linkedin_graph_sync_runs",
                    {},
                    Exception('relation "linkedin_graph_sync_runs" does not exist'),
                )
            ),
        ),
        patch("app.tasks.linkedin_graph.logger.warning") as mock_warning,
    ):
        result = await _cleanup_orphaned_sessions()

    assert result == {"cleaned_up": 0}
    mock_db.rollback.assert_awaited_once()
    mock_warning.assert_called_once()


@pytest.mark.asyncio()
async def test_cleanup_orphaned_sessions_reraises_other_programming_errors():
    from app.tasks.linkedin_graph import _cleanup_orphaned_sessions

    mock_db = AsyncMock()
    mock_db.rollback = AsyncMock()

    with (
        patch(
            "app.tasks.linkedin_graph.async_session",
            return_value=_make_session(mock_db),
        ),
        patch(
            "app.tasks.linkedin_graph.cleanup_orphaned_sync_sessions",
            new=AsyncMock(
                side_effect=ProgrammingError(
                    "SELECT * FROM linkedin_graph_sync_runs",
                    {},
                    Exception("some other programming error"),
                )
            ),
        ),
    ):
        with pytest.raises(ProgrammingError):
            await _cleanup_orphaned_sessions()

    mock_db.rollback.assert_not_awaited()
