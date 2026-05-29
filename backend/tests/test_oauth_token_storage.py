import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet
import pytest

from app.config import settings
from app.models.settings import UserSettings
from app.services import gmail_service, outlook_service
from app.services.oauth_token_crypto import (
    OAuthTokenEncryptionNotConfiguredError,
    decrypt_refresh_token,
    encrypt_refresh_token,
    is_encrypted_refresh_token,
)

pytestmark = pytest.mark.asyncio


def _set_token_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "token_encryption_primary_version", "v1")
    monkeypatch.setattr(
        settings,
        "token_encryption_keys",
        {"v1": Fernet.generate_key().decode("utf-8")},
    )


def _mock_db_for_settings(user_settings: UserSettings) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = user_settings
    db = AsyncMock()
    db.execute.return_value = result
    return db


async def test_connect_gmail_encrypts_refresh_token(monkeypatch: pytest.MonkeyPatch):
    _set_token_key(monkeypatch)
    user_id = uuid.uuid4()
    user_settings = UserSettings(user_id=user_id)
    db = _mock_db_for_settings(user_settings)

    with patch.object(
        gmail_service,
        "exchange_code",
        new=AsyncMock(return_value={"refresh_token": "gmail-refresh-token"}),
    ):
        connected = await gmail_service.connect_gmail(
            db,
            user_id,
            code="oauth-code",
            redirect_uri="http://localhost/callback",
        )

    assert connected is True
    assert user_settings.gmail_connected is True
    assert user_settings.gmail_refresh_token != "gmail-refresh-token"
    assert is_encrypted_refresh_token(user_settings.gmail_refresh_token)
    assert decrypt_refresh_token(user_settings.gmail_refresh_token) == "gmail-refresh-token"
    db.commit.assert_awaited_once()


async def test_connect_outlook_encrypts_refresh_token(monkeypatch: pytest.MonkeyPatch):
    _set_token_key(monkeypatch)
    user_id = uuid.uuid4()
    user_settings = UserSettings(user_id=user_id)
    db = _mock_db_for_settings(user_settings)

    with patch.object(
        outlook_service,
        "exchange_code",
        new=AsyncMock(return_value={"refresh_token": "outlook-refresh-token"}),
    ):
        connected = await outlook_service.connect_outlook(
            db,
            user_id,
            code="oauth-code",
            redirect_uri="http://localhost/callback",
        )

    assert connected is True
    assert user_settings.outlook_connected is True
    assert user_settings.outlook_refresh_token != "outlook-refresh-token"
    assert is_encrypted_refresh_token(user_settings.outlook_refresh_token)
    assert (
        decrypt_refresh_token(user_settings.outlook_refresh_token)
        == "outlook-refresh-token"
    )
    db.commit.assert_awaited_once()


async def test_plaintext_gmail_token_forces_reconnect(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_token_key(monkeypatch)
    user_id = uuid.uuid4()
    user_settings = UserSettings(
        user_id=user_id,
        gmail_connected=True,
        gmail_refresh_token="legacy-plaintext-token",
    )
    db = AsyncMock()

    with pytest.raises(ValueError, match="reconnected"):
        await gmail_service.get_access_token(db, user_id, user_settings)

    assert user_settings.gmail_connected is False
    assert user_settings.gmail_refresh_token is None
    db.commit.assert_awaited_once()


async def test_plaintext_outlook_token_forces_reconnect(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_token_key(monkeypatch)
    user_id = uuid.uuid4()
    user_settings = UserSettings(
        user_id=user_id,
        outlook_connected=True,
        outlook_refresh_token="legacy-plaintext-token",
    )
    db = AsyncMock()

    with pytest.raises(ValueError, match="reconnected"):
        await outlook_service.get_access_token(db, user_id, user_settings)

    assert user_settings.outlook_connected is False
    assert user_settings.outlook_refresh_token is None
    db.commit.assert_awaited_once()


async def test_missing_key_version_does_not_clear_gmail_connection(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_token_key(monkeypatch)
    user_id = uuid.uuid4()
    encrypted_token = encrypt_refresh_token("gmail-refresh-token")
    monkeypatch.setattr(settings, "token_encryption_keys", {})
    user_settings = UserSettings(
        user_id=user_id,
        gmail_connected=True,
        gmail_refresh_token=encrypted_token,
    )
    db = AsyncMock()

    with pytest.raises(OAuthTokenEncryptionNotConfiguredError):
        await gmail_service.get_access_token(db, user_id, user_settings)

    assert user_settings.gmail_connected is True
    assert user_settings.gmail_refresh_token == encrypted_token
    db.commit.assert_not_awaited()
