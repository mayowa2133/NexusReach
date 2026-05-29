from cryptography.fernet import Fernet
import pytest

from app.config import settings
from app.services.oauth_token_crypto import (
    OAuthTokenEncryptionNotConfiguredError,
    OAuthTokenReconnectionRequiredError,
    decrypt_refresh_token,
    encrypt_refresh_token,
    is_encrypted_refresh_token,
)


def _set_token_key(monkeypatch: pytest.MonkeyPatch, version: str = "v1") -> str:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "token_encryption_primary_version", version)
    monkeypatch.setattr(settings, "token_encryption_keys", {version: key})
    return key


def test_encrypt_refresh_token_stores_versioned_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_token_key(monkeypatch)

    stored = encrypt_refresh_token("refresh-token-value")

    assert stored.startswith("nexusreach_oauth_token:v1:")
    assert stored != "refresh-token-value"
    assert is_encrypted_refresh_token(stored) is True
    assert decrypt_refresh_token(stored) == "refresh-token-value"


def test_decrypt_refresh_token_rejects_plaintext():
    with pytest.raises(OAuthTokenReconnectionRequiredError):
        decrypt_refresh_token("plain-refresh-token")


def test_encrypt_refresh_token_requires_configured_primary_key(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "token_encryption_primary_version", "v2")
    monkeypatch.setattr(settings, "token_encryption_keys", {})

    with pytest.raises(OAuthTokenEncryptionNotConfiguredError):
        encrypt_refresh_token("refresh-token-value")


def test_decrypt_refresh_token_requires_matching_key_version(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_token_key(monkeypatch, "v1")
    stored = encrypt_refresh_token("refresh-token-value")
    monkeypatch.setattr(settings, "token_encryption_keys", {})

    with pytest.raises(OAuthTokenEncryptionNotConfiguredError):
        decrypt_refresh_token(stored)
