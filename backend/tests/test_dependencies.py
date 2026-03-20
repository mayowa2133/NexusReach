"""Tests for auth dependencies and user bootstrap."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.dependencies import AuthenticatedUser, get_current_auth_user, get_or_create_user

pytestmark = pytest.mark.asyncio


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


async def test_get_or_create_user_uses_jwt_email_for_new_user():
    auth_user = AuthenticatedUser(user_id=uuid.uuid4(), email="person@example.com")
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    user = await get_or_create_user(auth_user, db)

    assert user.email == "person@example.com"
    assert db.add.call_count == 3


async def test_get_or_create_user_backfills_blank_email_and_defaults():
    auth_user = AuthenticatedUser(user_id=uuid.uuid4(), email="person@example.com")
    existing_user = SimpleNamespace(id=auth_user.user_id, email="")
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(existing_user),
            _ScalarResult(None),
            _ScalarResult(None),
        ]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    user = await get_or_create_user(auth_user, db)

    assert user.email == "person@example.com"
    assert db.add.call_count == 2


async def test_get_current_auth_user_returns_configured_dev_user(monkeypatch):
    dev_user_id = uuid.uuid4()
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "dev_user_id", dev_user_id)
    monkeypatch.setattr(settings, "dev_user_email", "DevUser@example.com")

    auth_user = await get_current_auth_user(None)

    assert auth_user.user_id == dev_user_id
    assert auth_user.email == "devuser@example.com"
