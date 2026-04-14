"""Gmail integration — OAuth consent flow and draft staging via Gmail API."""

import asyncio
import base64
import logging
import time
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import UserSettings

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1"
SCOPES = "https://www.googleapis.com/auth/gmail.compose"

# In-memory token cache: {user_id: (access_token, expires_at_epoch)}
_token_cache: dict[uuid.UUID, tuple[str, float]] = {}
_token_locks: dict[uuid.UUID, asyncio.Lock] = {}

# Refresh the token 60 seconds before actual expiry
_EXPIRY_BUFFER_SECONDS = 60


def _get_lock(user_id: uuid.UUID) -> asyncio.Lock:
    """Get or create a per-user lock for token refresh."""
    if user_id not in _token_locks:
        _token_locks[user_id] = asyncio.Lock()
    return _token_locks[user_id]


def get_auth_url(redirect_uri: str, state: str = "") -> str:
    """Generate the Google OAuth consent URL."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for tokens."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _refresh_access_token_uncached(refresh_token: str) -> tuple[str, int]:
    """Refresh an expired access token. Returns (access_token, expires_in_seconds)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["access_token"], int(data.get("expires_in", 3600))


async def refresh_access_token(refresh_token: str) -> str:
    """Refresh an expired access token (compatibility wrapper)."""
    access_token, _ = await _refresh_access_token_uncached(refresh_token)
    return access_token


async def _get_access_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_settings: UserSettings,
) -> str:
    """Get a valid access token, using cache and per-user locking.

    If the cached token is still valid, returns it immediately.
    Otherwise, refreshes under a lock so concurrent requests don't race.
    If the refresh token is revoked/invalid, disconnects Gmail and raises.
    """
    now = time.time()
    cached = _token_cache.get(user_id)
    if cached:
        token, expires_at = cached
        if now < expires_at - _EXPIRY_BUFFER_SECONDS:
            return token

    lock = _get_lock(user_id)
    async with lock:
        # Double-check after acquiring lock — another coroutine may have refreshed
        cached = _token_cache.get(user_id)
        if cached:
            token, expires_at = cached
            if now < expires_at - _EXPIRY_BUFFER_SECONDS:
                return token

        refresh_token = user_settings.gmail_refresh_token
        if not refresh_token:
            raise ValueError("Gmail not connected. Please connect Gmail in Settings.")

        try:
            access_token, expires_in = await _refresh_access_token_uncached(refresh_token)
        except httpx.HTTPStatusError as exc:
            # 400/401 from Google means the refresh token is revoked or invalid.
            # Disconnect Gmail so the user isn't stuck in a retry loop.
            if exc.response.status_code in (400, 401):
                logger.warning(
                    "Gmail refresh token invalid for user %s — disconnecting",
                    user_id,
                )
                user_settings.gmail_refresh_token = None
                user_settings.gmail_connected = False
                await db.commit()
                _token_cache.pop(user_id, None)
            raise ValueError(
                "Gmail session expired. Please reconnect Gmail in Settings."
            ) from exc

        _token_cache[user_id] = (access_token, now + expires_in)
        return access_token


async def connect_gmail(
    db: AsyncSession,
    user_id: uuid.UUID,
    code: str,
    redirect_uri: str,
) -> bool:
    """Complete Gmail OAuth — exchange code and store refresh token."""
    tokens = await exchange_code(code, redirect_uri)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh token received. Please re-authorize with consent.")

    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        raise ValueError("User settings not found.")

    user_settings.gmail_refresh_token = refresh_token
    user_settings.gmail_connected = True
    await db.commit()

    # Clear any stale cached token
    _token_cache.pop(user_id, None)
    return True


async def disconnect_gmail(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> bool:
    """Disconnect Gmail — remove stored tokens."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        raise ValueError("User settings not found.")

    user_settings.gmail_refresh_token = None
    user_settings.gmail_connected = False
    await db.commit()

    # Clear cached token
    _token_cache.pop(user_id, None)
    return True


async def create_draft(
    db: AsyncSession,
    user_id: uuid.UUID,
    to_email: str,
    subject: str,
    body: str,
    from_name: str | None = None,
) -> dict:
    """Create a draft email in the user's Gmail account.

    Returns:
        {"draft_id": str, "message_id": str} on success.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings or not user_settings.gmail_refresh_token:
        raise ValueError("Gmail not connected. Please connect Gmail in Settings.")

    # Get fresh access token (cached + locked)
    access_token = await _get_access_token(db, user_id, user_settings)

    # Build MIME email
    message = MIMEMultipart("alternative")
    message["to"] = to_email
    message["subject"] = subject
    if from_name:
        message["from"] = from_name

    # Plain text body
    text_part = MIMEText(body, "plain")
    message.attach(text_part)

    # HTML body (simple paragraph formatting)
    html_body = body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    html_part = MIMEText(f"<p>{html_body}</p>", "html")
    message.attach(html_part)

    # Encode for Gmail API
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GMAIL_API_URL}/users/me/drafts",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"message": {"raw": raw}},
        )
        resp.raise_for_status()
        draft_data = resp.json()

    return {
        "draft_id": draft_data.get("id", ""),
        "message_id": draft_data.get("message", {}).get("id", ""),
        "provider": "gmail",
    }


async def send_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    to_email: str,
    subject: str,
    body: str,
    from_name: str | None = None,
) -> dict:
    """Send an email directly via the user's Gmail account.

    Returns:
        {"message_id": str, "provider": "gmail"} on success.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings or not user_settings.gmail_refresh_token:
        raise ValueError("Gmail not connected. Please connect Gmail in Settings.")

    access_token = await _get_access_token(db, user_id, user_settings)

    # Build MIME email
    message = MIMEMultipart("alternative")
    message["to"] = to_email
    message["subject"] = subject
    if from_name:
        message["from"] = from_name

    text_part = MIMEText(body, "plain")
    message.attach(text_part)

    html_body = body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    html_part = MIMEText(f"<p>{html_body}</p>", "html")
    message.attach(html_part)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GMAIL_API_URL}/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
        resp.raise_for_status()
        send_data = resp.json()

    return {
        "message_id": send_data.get("id", ""),
        "provider": "gmail",
    }
