"""Gmail integration — OAuth consent flow and draft staging via Gmail API."""

import base64
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import UserSettings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1"
SCOPES = "https://www.googleapis.com/auth/gmail.compose"


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
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


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


async def refresh_access_token(refresh_token: str) -> str:
    """Refresh an expired access token."""
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
        return resp.json()["access_token"]


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

    # Get fresh access token
    access_token = await refresh_access_token(user_settings.gmail_refresh_token)

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
