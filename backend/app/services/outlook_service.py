"""Outlook/Microsoft integration — OAuth consent flow and draft staging via Graph API."""

import uuid
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import UserSettings

MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_API_URL = "https://graph.microsoft.com/v1.0"
SCOPES = "Mail.ReadWrite offline_access"


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


async def refresh_access_token(refresh_token: str) -> str:
    """Refresh an expired access token."""
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
            return resp.json()["access_token"]
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            "Outlook session expired. Please reconnect Outlook in Settings."
        ) from exc


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

    user_settings.outlook_refresh_token = refresh_token
    user_settings.outlook_connected = True
    await db.commit()
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

    # Get fresh access token
    access_token = await refresh_access_token(user_settings.outlook_refresh_token)

    # Build Graph API message
    html_body = body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    message_payload = {
        "subject": subject,
        "body": {
            "contentType": "HTML",
            "content": f"<p>{html_body}</p>",
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
