"""Tests for company persistence — concurrency-safe get_or_create."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError


class _SavepointCM:
    """Minimal async context manager standing in for db.begin_nested()."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False  # propagate the IntegrityError, like a real savepoint


@pytest.mark.asyncio()
async def test_get_or_create_company_recovers_from_concurrent_insert():
    """A racing duplicate insert is recovered by re-selecting the winner's row.

    Simulates two concurrent get_or_create_company calls for the same
    (user_id, normalized_name): our INSERT loses and raises a UniqueViolation,
    and we transparently return the row the other transaction created.
    """
    from app.services.people import persistence

    user_id = uuid.uuid4()
    existing_company = MagicMock(name="existing_company")

    no_row = MagicMock()
    no_row.scalars.return_value.first.return_value = None
    found = MagicMock()
    found.scalars.return_value.first.return_value = existing_company

    db = MagicMock()
    # 1st execute = initial lookup (miss); 2nd = post-conflict re-select (hit).
    db.execute = AsyncMock(side_effect=[no_row, found])
    db.flush = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("duplicate key"))
    )
    db.begin_nested = MagicMock(return_value=_SavepointCM())
    db.add = MagicMock()
    db.expunge = MagicMock()
    db.__contains__ = MagicMock(return_value=True)

    with patch.object(
        persistence.apollo_client, "search_company", new=AsyncMock(return_value=None)
    ):
        result = await persistence.get_or_create_company(db, user_id, "RTX")

    assert result is existing_company
    db.expunge.assert_called_once()
    assert db.execute.await_count == 2  # initial lookup + post-conflict re-select


@pytest.mark.asyncio()
async def test_get_or_create_company_reraises_when_row_still_missing():
    """If the conflict wasn't the company-name unique race, don't swallow it."""
    from app.services.people import persistence

    user_id = uuid.uuid4()

    no_row = MagicMock()
    no_row.scalars.return_value.first.return_value = None

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[no_row, no_row])  # re-select also empty
    db.flush = AsyncMock(
        side_effect=IntegrityError("INSERT", {}, Exception("some other constraint"))
    )
    db.begin_nested = MagicMock(return_value=_SavepointCM())
    db.add = MagicMock()
    db.expunge = MagicMock()
    db.__contains__ = MagicMock(return_value=True)

    with patch.object(
        persistence.apollo_client, "search_company", new=AsyncMock(return_value=None)
    ):
        with pytest.raises(IntegrityError):
            await persistence.get_or_create_company(db, user_id, "RTX")
