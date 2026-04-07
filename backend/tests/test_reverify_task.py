"""Tests for the stale contact re-verification Celery task."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_person(*, company=None, person_id=None):
    """Create a mock Person for testing."""
    person = MagicMock()
    person.id = person_id or uuid4()
    person.user_id = uuid4()
    person.full_name = "Test Person"
    person.company = company
    return person


def _make_company(name="TestCo"):
    company = MagicMock()
    company.name = name
    company.domain = "testco.com"
    company.domain_trusted = True
    company.public_identity_slugs = None
    company.identity_hints = None
    return company


def _mock_session(stale_people):
    """Build a mock async_session context manager returning given people."""
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = stale_people
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.add = MagicMock()

    class FakeSession:
        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, *args):
            pass

    return FakeSession, mock_db


_PATCH_PREFIX = "app.tasks.reverify"


@pytest.mark.asyncio()
async def test_skips_contacts_without_company():
    person = _make_person(company=None)
    SessionCls, _ = _mock_session([person])

    with (
        patch(f"{_PATCH_PREFIX}.async_session", return_value=SessionCls()),
        patch(f"{_PATCH_PREFIX}.settings") as mock_settings,
    ):
        mock_settings.reverify_stale_days = 14
        mock_settings.reverify_batch_size = 20

        from app.tasks.reverify import _reverify_stale_contacts

        result = await _reverify_stale_contacts()

    assert result["skipped"] == 1
    assert result["verified"] == 0


@pytest.mark.asyncio()
async def test_verifies_stale_contact():
    company = _make_company()
    person = _make_person(company=company)
    mock_verification = MagicMock()

    SessionCls, mock_db = _mock_session([person])

    with (
        patch(f"{_PATCH_PREFIX}.async_session", return_value=SessionCls()),
        patch(f"{_PATCH_PREFIX}.settings") as mock_settings,
        patch(f"{_PATCH_PREFIX}._verify_person", new_callable=AsyncMock) as mock_verify,
        patch(f"{_PATCH_PREFIX}._apply_verification_result") as mock_apply,
        patch(f"{_PATCH_PREFIX}.effective_public_identity_slugs", return_value=["testco"]),
    ):
        mock_settings.reverify_stale_days = 14
        mock_settings.reverify_batch_size = 20
        mock_verify.return_value = mock_verification

        from app.tasks.reverify import _reverify_stale_contacts

        result = await _reverify_stale_contacts()

    assert result["verified"] == 1
    assert result["failed"] == 0
    mock_verify.assert_called_once()
    mock_apply.assert_called_once_with(person, mock_verification)
    mock_db.commit.assert_called()


@pytest.mark.asyncio()
async def test_isolates_individual_failures():
    company = _make_company()
    person1 = _make_person(company=company)
    person2 = _make_person(company=company)

    SessionCls, mock_db = _mock_session([person1, person2])

    with (
        patch(f"{_PATCH_PREFIX}.async_session", return_value=SessionCls()),
        patch(f"{_PATCH_PREFIX}.settings") as mock_settings,
        patch(f"{_PATCH_PREFIX}._verify_person", new_callable=AsyncMock) as mock_verify,
        patch(f"{_PATCH_PREFIX}._apply_verification_result"),
        patch(f"{_PATCH_PREFIX}.effective_public_identity_slugs", return_value=["testco"]),
    ):
        mock_settings.reverify_stale_days = 14
        mock_settings.reverify_batch_size = 20
        # First person fails, second succeeds
        mock_verify.side_effect = [RuntimeError("network error"), MagicMock()]

        from app.tasks.reverify import _reverify_stale_contacts

        result = await _reverify_stale_contacts()

    assert result["failed"] == 1
    assert result["verified"] == 1
    assert result["total_stale"] == 2
    # First failure should trigger rollback, second should commit
    mock_db.rollback.assert_called_once()
    mock_db.commit.assert_called()


@pytest.mark.asyncio()
async def test_respects_batch_size():
    """The query should use settings.reverify_batch_size as limit."""
    SessionCls, mock_db = _mock_session([])

    with (
        patch(f"{_PATCH_PREFIX}.async_session", return_value=SessionCls()),
        patch(f"{_PATCH_PREFIX}.settings") as mock_settings,
    ):
        mock_settings.reverify_stale_days = 14
        mock_settings.reverify_batch_size = 5

        from app.tasks.reverify import _reverify_stale_contacts

        result = await _reverify_stale_contacts()

    assert result["total_stale"] == 0
    mock_db.execute.assert_called_once()
