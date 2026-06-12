"""Outlook/Microsoft integration — OAuth consent flow and draft staging via Graph API."""

import asyncio
import html
import logging
import time
import uuid
from urllib.parse import urlencode

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import UserSettings
from app.services.oauth_token_crypto import (
    OAuthTokenReconnectionRequiredError,
    decrypt_refresh_token,
    encrypt_refresh_token,
)

logger = logging.getLogger(__name__)

MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_API_URL = "https://graph.microsoft.com/v1.0"
SCOPES = "Mail.ReadWrite Mail.Send offline_access"

# In-memory token cache mirrors the Gmail service (audit H11) so we don't hit
# the Microsoft token endpoint on every Graph call: {user_id: (token, expiry)}
_token_cache: dict[uuid.UUID, tuple[str, float]] = {}
_token_locks: dict[uuid.UUID, asyncio.Lock] = {}

# Refresh the token this many seconds before its actual expiry.
_EXPIRY_BUFFER_SECONDS = 60


def _get_lock(user_id: uuid.UUID) -> asyncio.Lock:
    """Get or create a per-user lock for token refresh."""
    if user_id not in _token_locks:
        _token_locks[user_id] = asyncio.Lock()
    return _token_locks[user_id]


def _body_to_html(body: str) -> str:
    """Escape the message body before paragraph/line formatting (audit M14)."""
    escaped = html.escape(body or "")
    formatted = escaped.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f"<p>{formatted}</p>"


def get_auth_url(redirect_uri: str, state: str = "") -> str:
    """Generate the Microsoft OAuth consent URL."""
    params = {
        "client_id": settings.microsoft_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "response_mode": "query",
        "state": state,
    }
    return f"{MS_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for tokens."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            MS_TOKEN_URL,
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _refresh_access_token_uncached(refresh_token: str) -> tuple[str, int]:
    """Refresh an access token. Returns (access_token, expires_in_seconds)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                MS_TOKEN_URL,
                data={
                    "client_id": settings.microsoft_client_id,
                    "client_secret": settings.microsoft_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": SCOPES,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["access_token"], int(data.get("expires_in", 3600))
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            "Outlook session expired. Please reconnect Outlook in Settings."
        ) from exc


async def refresh_access_token(refresh_token: str) -> str:
    """Refresh an expired access token (compatibility wrapper)."""
    access_token, _ = await _refresh_access_token_uncached(refresh_token)
    return access_token


async def get_access_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_settings: UserSettings,
) -> str:
    """Return a valid Outlook access token, using cache and per-user locking.

    Mirrors the Gmail service (audit H11): a cached token within its TTL is
    returned immediately; otherwise it refreshes under a per-user lock so
    concurrent Graph calls don't each hit the token endpoint.
    """
    now = time.time()
    cached = _token_cache.get(user_id)
    if cached:
        token, expires_at = cached
        if now < expires_at - _EXPIRY_BUFFER_SECONDS:
            return token

    lock = _get_lock(user_id)
    async with lock:
        # Double-check after acquiring the lock — another coroutine may have refreshed.
        cached = _token_cache.get(user_id)
        if cached:
            token, expires_at = cached
            if now < expires_at - _EXPIRY_BUFFER_SECONDS:
                return token

        stored_refresh_token = user_settings.outlook_refresh_token
        if not stored_refresh_token:
            raise ValueError("Outlook not connected. Please connect Outlook in Settings.")

        try:
            refresh_token = decrypt_refresh_token(stored_refresh_token)
        except OAuthTokenReconnectionRequiredError as exc:
            user_settings.outlook_refresh_token = None
            user_settings.outlook_connected = False
            await db.commit()
            _token_cache.pop(user_id, None)
            raise ValueError(
                "Outlook must be reconnected before it can be used."
            ) from exc

        try:
            access_token, expires_in = await _refresh_access_token_uncached(refresh_token)
        except ValueError:
            user_settings.outlook_refresh_token = None
            user_settings.outlook_connected = False
            await db.commit()
            _token_cache.pop(user_id, None)
            raise
        except Exception as exc:
            raise ValueError(
                "Outlook session expired. Please reconnect Outlook in Settings."
            ) from exc

        _token_cache[user_id] = (access_token, now + expires_in)
        return access_token


async def connect_outlook(
    db: AsyncSession,
    user_id: uuid.UUID,
    code: str,
    redirect_uri: str,
) -> bool:
    """Complete Outlook OAuth — exchange code and store refresh token."""
    tokens = await exchange_code(code, redirect_uri)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh token received. Please re-authorize.")

    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        raise ValueError("User settings not found.")

    user_settings.outlook_refresh_token = encrypt_refresh_token(refresh_token)
    user_settings.outlook_connected = True
    await db.commit()

    # Clear any stale cached token from a prior connection.
    _token_cache.pop(user_id, None)
    return True


async def disconnect_outlook(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> bool:
    """Disconnect Outlook — remove stored tokens."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        raise ValueError("User settings not found.")

    user_settings.outlook_refresh_token = None
    user_settings.outlook_connected = False
    await db.commit()

    # Clear cached token so a disconnected account can't keep sending.
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
    """Create a draft email in the user's Outlook account via Microsoft Graph.

    Returns:
        {"draft_id": str, "provider": "outlook"} on success.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings or not user_settings.outlook_refresh_token:
        raise ValueError("Outlook not connected. Please connect Outlook in Settings.")

    access_token = await get_access_token(db, user_id, user_settings)

    # Build Graph API message
    message_payload = {
        "subject": subject,
        "body": {
            "contentType": "HTML",
            "content": _body_to_html(body),
        },
        "toRecipients": [
            {"emailAddress": {"address": to_email}}
        ],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GRAPH_API_URL}/me/messages",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=message_payload,
        )
        resp.raise_for_status()
        draft_data = resp.json()

    return {
        "draft_id": draft_data.get("id", ""),
        "message_id": draft_data.get("id", ""),
        "provider": "outlook",
    }


async def send_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    to_email: str,
    subject: str,
    body: str,
    from_name: str | None = None,
) -> dict:
    """Send an email directly via the user's Outlook account using Microsoft Graph.

    Returns:
        {"message_id": str, "provider": "outlook"} on success.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings or not user_settings.outlook_refresh_token:
        raise ValueError("Outlook not connected. Please connect Outlook in Settings.")

    access_token = await get_access_token(db, user_id, user_settings)

    send_payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": _body_to_html(body),
            },
            "toRecipients": [
                {"emailAddress": {"address": to_email}}
            ],
        },
        "saveToSentItems": True,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GRAPH_API_URL}/me/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=send_payload,
        )
        if resp.status_code == 403:
            raise ValueError(
                "Outlook lacks send permission. Please disconnect and reconnect "
                "Outlook in Settings to grant the Mail.Send scope."
            )
        resp.raise_for_status()

    return {
        "message_id": "",
        "provider": "outlook",
    }


async def check_draft_sent(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    provider_message_id: str,
) -> dict:
    """Check whether a staged Outlook draft has actually been sent.

    Microsoft Graph exposes an ``isDraft`` boolean and a ``sentDateTime``
    on the message. When the user sends from the Outlook UI the draft is
    moved out of the Drafts folder and ``isDraft`` flips to False. A 404
    likely means the draft was discarded — treat as "not sent" / unknown.

    Returns:
        {"sent": bool, "message_id": str | None, "is_draft": bool}
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings or not user_settings.outlook_refresh_token:
        raise ValueError("Outlook not connected.")

    access_token = await get_access_token(db, user_id, user_settings)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{GRAPH_API_URL}/me/messages/{provider_message_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "id,isDraft,sentDateTime,parentFolderId"},
        )

    if resp.status_code == 404:
        return {"sent": False, "message_id": None, "is_draft": False}
    resp.raise_for_status()
    data = resp.json()
    is_draft = bool(data.get("isDraft", True))
    sent_date = data.get("sentDateTime")
    return {
        "sent": (not is_draft) and bool(sent_date),
        "message_id": data.get("id"),
        "is_draft": is_draft,
    }


async def check_reply_received(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    provider_message_id: str,
    since: datetime,
) -> dict:
    """Check whether the conversation of a sent Outlook message got a reply.

    Resolves the message's ``conversationId`` and looks for inbox messages
    in the same conversation received after ``since``. Restricting to the
    inbox folder means only messages the user received count as replies.
    A 404 on the original message means it was deleted - report no reply.

    Returns:
        {"replied": bool, "reply_count": int, "last_reply_at": str | None}
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    if not user_settings or not user_settings.outlook_refresh_token:
        raise ValueError("Outlook not connected.")

    access_token = await get_access_token(db, user_id, user_settings)
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=15) as client:
        msg_resp = await client.get(
            f"{GRAPH_API_URL}/me/messages/{provider_message_id}",
            headers=headers,
            params={"$select": "id,conversationId"},
        )
        if msg_resp.status_code == 404:
            return {"replied": False, "reply_count": 0, "last_reply_at": None}
        msg_resp.raise_for_status()
        conversation_id = msg_resp.json().get("conversationId")
        if not conversation_id:
            return {"replied": False, "reply_count": 0, "last_reply_at": None}

        since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        escaped = conversation_id.replace("'", "''")
        list_resp = await client.get(
            f"{GRAPH_API_URL}/me/mailFolders/inbox/messages",
            headers=headers,
            params={
                "$filter": (
                    f"conversationId eq '{escaped}' "
                    f"and receivedDateTime ge {since_iso}"
                ),
                "$select": "id,receivedDateTime",
                "$top": "10",
            },
        )
        list_resp.raise_for_status()

    received = [
        item.get("receivedDateTime")
        for item in list_resp.json().get("value") or []
        if item.get("receivedDateTime")
    ]
    return {
        "replied": bool(received),
        "reply_count": len(received),
        "last_reply_at": max(received) if received else None,
    }
