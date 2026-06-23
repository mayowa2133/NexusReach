"""Tests for job alert Celery task guards."""

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
async def test_send_all_digests_skips_when_preferences_table_missing():
    from app.tasks.job_alerts import _send_all_digests

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT job_alert_preferences.user_id FROM job_alert_preferences",
        {},
        Exception('relation "job_alert_preferences" does not exist'),
    )
    mock_db.rollback = AsyncMock()

    with (
        patch("app.tasks.job_alerts.async_session", return_value=_make_session(mock_db)),
        patch("app.tasks.job_alerts.logger.warning") as mock_warning,
    ):
        result = await _send_all_digests()

    assert result == {"users_checked": 0, "digests_sent": 0, "failures": 0}
    mock_db.rollback.assert_awaited_once()
    mock_warning.assert_called_once()


@pytest.mark.asyncio()
async def test_send_all_digests_reraises_other_programming_errors():
    from app.tasks.job_alerts import _send_all_digests

    mock_db = AsyncMock()
    mock_db.execute.side_effect = ProgrammingError(
        "SELECT job_alert_preferences.user_id FROM job_alert_preferences",
        {},
        Exception("some other programming error"),
    )
    mock_db.rollback = AsyncMock()

    with patch("app.tasks.job_alerts.async_session", return_value=_make_session(mock_db)):
        with pytest.raises(ProgrammingError):
            await _send_all_digests()

    mock_db.rollback.assert_not_awaited()
