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
SCOPES = "Mail.ReadWrite Mail.Send offline_access"


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

    try:
        access_token = await refresh_access_token(user_settings.outlook_refresh_token)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            "Outlook session expired. Please reconnect Outlook in Settings."
        ) from exc

    html_body = body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    send_payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": f"<p>{html_body}</p>",
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

    access_token = await refresh_access_token(user_settings.outlook_refresh_token)

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
