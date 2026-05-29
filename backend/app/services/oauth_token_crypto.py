"""Versioned encryption helpers for stored OAuth refresh tokens."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

TOKEN_PREFIX = "nexusreach_oauth_token"


class OAuthTokenCryptoError(ValueError):
    """Base class for OAuth token encryption/decryption failures."""


class OAuthTokenEncryptionNotConfiguredError(OAuthTokenCryptoError):
    """Raised when token encryption keys are missing or invalid."""


class OAuthTokenReconnectionRequiredError(OAuthTokenCryptoError):
    """Raised when a stored token cannot be decrypted and must be reconnected."""


def _fernet_for_version(version: str) -> Fernet:
    raw_key = settings.token_encryption_keys.get(version)
    if not raw_key:
        raise OAuthTokenEncryptionNotConfiguredError(
            f"Missing OAuth token encryption key for version '{version}'."
        )
    try:
        return Fernet(raw_key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise OAuthTokenEncryptionNotConfiguredError(
            f"Invalid OAuth token encryption key for version '{version}'."
        ) from exc


def is_encrypted_refresh_token(value: str | None) -> bool:
    """Return True when a stored refresh token uses the encrypted token format."""
    return bool(value and value.startswith(f"{TOKEN_PREFIX}:"))


def encrypt_refresh_token(refresh_token: str) -> str:
    """Encrypt a provider refresh token with the configured primary key."""
    token = refresh_token.strip()
    if not token:
        raise ValueError("Refresh token cannot be empty.")

    version = settings.token_encryption_primary_version.strip()
    if not version:
        raise OAuthTokenEncryptionNotConfiguredError(
            "NEXUSREACH_TOKEN_ENCRYPTION_PRIMARY_VERSION is empty."
        )
    fernet = _fernet_for_version(version)
    encrypted = fernet.encrypt(token.encode("utf-8")).decode("utf-8")
    return f"{TOKEN_PREFIX}:{version}:{encrypted}"


def decrypt_refresh_token(stored_token: str | None) -> str:
    """Decrypt a stored provider refresh token.

    Plaintext or malformed values are treated as reconnect-required, not as a
    backwards-compatible plaintext fallback.
    """
    if not stored_token:
        raise OAuthTokenReconnectionRequiredError(
            "OAuth provider is not connected. Please reconnect in Settings."
        )

    parts = stored_token.split(":", 2)
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise OAuthTokenReconnectionRequiredError(
            "Stored OAuth token must be reconnected before it can be used."
        )

    _, version, encrypted = parts
    fernet = _fernet_for_version(version)
    try:
        return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise OAuthTokenReconnectionRequiredError(
            "Stored OAuth token could not be decrypted. Please reconnect in Settings."
        ) from exc
