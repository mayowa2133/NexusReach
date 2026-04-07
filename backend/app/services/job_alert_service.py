"""Job alert service — manage alert preferences and send email digests.

When new jobs are discovered from companies a user watches (or has starred),
this service sends a digest email through their connected email provider.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.job import Job
from app.models.job_alert import JobAlertPreference
from app.models.settings import UserSettings
from app.models.user import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRUD — preferences
# ---------------------------------------------------------------------------


async def get_alert_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> JobAlertPreference:
    """Return the user's alert preferences, creating defaults if missing."""
    stmt = select(JobAlertPreference).where(JobAlertPreference.user_id == user_id)
    result = await db.execute(stmt)
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = JobAlertPreference(user_id=user_id)
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
    return prefs


async def update_alert_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: dict,
) -> JobAlertPreference:
    """Partially update alert preferences with validated fields."""
    prefs = await get_alert_preferences(db, user_id)
    for field, value in payload.items():
        if hasattr(prefs, field):
            setattr(prefs, field, value)
    await db.commit()
    await db.refresh(prefs)
    return prefs


# ---------------------------------------------------------------------------
# Watched company resolution
# ---------------------------------------------------------------------------


async def _resolve_watched_companies(
    db: AsyncSession,
    user_id: uuid.UUID,
    prefs: JobAlertPreference,
) -> set[str]:
    """Build the full set of lower-cased company names to alert on."""
    watched: set[str] = {c.lower().strip() for c in (prefs.watched_companies or [])}

    if prefs.use_starred_companies:
        stmt = select(Company.name).where(
            Company.user_id == user_id,
            Company.starred == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        for (name,) in result.all():
            watched.add(name.lower().strip())

    return watched


# ---------------------------------------------------------------------------
# New job matching
# ---------------------------------------------------------------------------


async def find_new_jobs_for_alert(
    db: AsyncSession,
    user_id: uuid.UUID,
    prefs: JobAlertPreference,
    since: datetime,
) -> list[Job]:
    """Find jobs created since *since* that match the user's alert criteria."""
    watched = await _resolve_watched_companies(db, user_id, prefs)
    if not watched:
        return []

    stmt = (
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.created_at >= since,
        )
        .order_by(Job.created_at.desc())
    )
    result = await db.execute(stmt)
    all_jobs = list(result.scalars().all())

    keyword_filters_lower = [kw.lower() for kw in (prefs.keyword_filters or [])]

    matching: list[Job] = []
    for job in all_jobs:
        company_lower = (job.company_name or "").lower().strip()
        if company_lower not in watched:
            continue

        # If keyword filters exist, job must match at least one
        if keyword_filters_lower:
            searchable = f"{job.title or ''} {job.description or ''} {job.location or ''}".lower()
            if not any(kw in searchable for kw in keyword_filters_lower):
                continue

        matching.append(job)

    return matching


# ---------------------------------------------------------------------------
# Email digest rendering
# ---------------------------------------------------------------------------


def _render_digest_html(jobs: list[Job], user_email: str) -> str:
    """Build a clean HTML email body for the job alert digest."""
    # Group jobs by company
    by_company: dict[str, list[Job]] = {}
    for job in jobs:
        company = job.company_name or "Unknown"
        by_company.setdefault(company, []).append(job)

    sections: list[str] = []
    for company, company_jobs in sorted(by_company.items()):
        items = []
        for job in company_jobs[:10]:  # Cap per company
            location = job.location or "Location not specified"
            link = f'<a href="{job.url}" style="color:#2563eb;text-decoration:none">{job.title}</a>' if job.url else job.title
            items.append(
                f'<li style="margin-bottom:8px">'
                f'{link}<br>'
                f'<span style="color:#6b7280;font-size:13px">{location}</span>'
                f'</li>'
            )
        remaining = len(company_jobs) - 10
        if remaining > 0:
            items.append(f'<li style="color:#6b7280">...and {remaining} more</li>')

        sections.append(
            f'<div style="margin-bottom:20px">'
            f'<h3 style="margin:0 0 8px 0;color:#111827">{company}</h3>'
            f'<ul style="margin:0;padding-left:20px">{"".join(items)}</ul>'
            f'</div>'
        )

    total = len(jobs)
    company_count = len(by_company)
    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#111827;margin-bottom:4px">New Job Alerts</h2>
      <p style="color:#6b7280;margin-top:0">{total} new posting{'s' if total != 1 else ''} from {company_count} watched compan{'ies' if company_count != 1 else 'y'}.</p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0">
      {''.join(sections)}
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0">
      <p style="color:#9ca3af;font-size:12px;margin:0">
        Sent by NexusReach job alerts. Manage your alert preferences in Settings.
      </p>
    </div>
    """


def _render_digest_text(jobs: list[Job]) -> str:
    """Plain text version of the digest."""
    lines: list[str] = [f"New Job Alerts — {len(jobs)} new posting(s)\n"]
    by_company: dict[str, list[Job]] = {}
    for job in jobs:
        by_company.setdefault(job.company_name or "Unknown", []).append(job)

    for company, company_jobs in sorted(by_company.items()):
        lines.append(f"\n{company}")
        lines.append("-" * len(company))
        for job in company_jobs[:10]:
            location = job.location or "Location not specified"
            lines.append(f"  • {job.title} — {location}")
            if job.url:
                lines.append(f"    {job.url}")

    lines.append("\n---\nSent by NexusReach job alerts. Manage in Settings.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email sending via connected providers
# ---------------------------------------------------------------------------


async def _resolve_email_provider(
    db: AsyncSession,
    user_id: uuid.UUID,
    prefs: JobAlertPreference,
) -> tuple[str, UserSettings]:
    """Resolve which email provider to use. Returns (provider_name, user_settings)."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        raise ValueError("User settings not found")

    preference = prefs.email_provider or "connected"

    if preference == "gmail" and user_settings.gmail_connected:
        return "gmail", user_settings
    if preference == "outlook" and user_settings.outlook_connected:
        return "outlook", user_settings
    if preference == "connected":
        if user_settings.gmail_connected:
            return "gmail", user_settings
        if user_settings.outlook_connected:
            return "outlook", user_settings

    raise ValueError("No email provider connected. Connect Gmail or Outlook in Settings.")


async def _send_via_gmail(
    user_settings: UserSettings,
    user_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> dict:
    """Send an email via Gmail API (send, not draft)."""
    from app.config import settings
    from app.services.gmail_service import GOOGLE_TOKEN_URL, GMAIL_API_URL

    if not user_settings.gmail_refresh_token:
        raise ValueError("Gmail not connected")

    # Refresh the access token
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": user_settings.gmail_refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        access_token = resp.json()["access_token"]

    # Build MIME message
    message = MIMEMultipart("alternative")
    message["to"] = user_email
    message["subject"] = subject
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GMAIL_API_URL}/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
        resp.raise_for_status()
        return resp.json()


async def _send_via_outlook(
    user_settings: UserSettings,
    user_email: str,
    subject: str,
    html_body: str,
) -> dict:
    """Send an email via Microsoft Graph API."""
    from app.config import settings
    from app.services.outlook_service import MS_TOKEN_URL, GRAPH_API_URL

    if not user_settings.outlook_refresh_token:
        raise ValueError("Outlook not connected")

    # Refresh token
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            MS_TOKEN_URL,
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "refresh_token": user_settings.outlook_refresh_token,
                "grant_type": "refresh_token",
                "scope": "Mail.Send offline_access",
            },
        )
        resp.raise_for_status()
        access_token = resp.json()["access_token"]

    # Send via Graph API
    message_payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [
                {"emailAddress": {"address": user_email}}
            ],
        },
        "saveToSentItems": "false",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GRAPH_API_URL}/me/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=message_payload,
        )
        resp.raise_for_status()
        return {"status": "sent"}


# ---------------------------------------------------------------------------
# Digest orchestration
# ---------------------------------------------------------------------------


async def send_digest_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Check for new matching jobs and send a digest email if any exist.

    Returns a dict with ``sent``, ``job_count``, ``provider``, and optional ``error``.
    """
    prefs = await get_alert_preferences(db, user_id)
    if not prefs.enabled:
        return {"sent": False, "job_count": 0, "provider": None, "error": "alerts_disabled"}

    # Determine lookback window based on frequency
    now = datetime.now(timezone.utc)
    if prefs.last_digest_sent_at:
        since = prefs.last_digest_sent_at
    else:
        freq_map = {"immediate": 1, "daily": 24, "weekly": 168}
        hours = freq_map.get(prefs.frequency, 24)
        since = now - timedelta(hours=hours)

    # Find matching jobs
    jobs = await find_new_jobs_for_alert(db, user_id, prefs, since)
    if not jobs:
        return {"sent": False, "job_count": 0, "provider": None, "error": None}

    # Resolve email provider and user email
    try:
        provider_name, user_settings = await _resolve_email_provider(db, user_id, prefs)
    except ValueError as exc:
        return {"sent": False, "job_count": len(jobs), "provider": None, "error": str(exc)}

    # Get user email for the To: field
    user_stmt = select(User.email).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user_email = user_result.scalar_one_or_none()
    if not user_email:
        return {"sent": False, "job_count": len(jobs), "provider": None, "error": "no_user_email"}

    # Render email content
    subject = f"NexusReach: {len(jobs)} new job{'s' if len(jobs) != 1 else ''} from your watched companies"
    html_body = _render_digest_html(jobs, user_email)
    text_body = _render_digest_text(jobs)

    # Send
    try:
        if provider_name == "gmail":
            await _send_via_gmail(user_settings, user_email, subject, html_body, text_body)
        elif provider_name == "outlook":
            await _send_via_outlook(user_settings, user_email, subject, html_body)
        else:
            return {"sent": False, "job_count": len(jobs), "provider": None, "error": "unknown_provider"}
    except Exception:
        logger.exception("Failed to send job alert digest for user %s", user_id)
        return {"sent": False, "job_count": len(jobs), "provider": provider_name, "error": "send_failed"}

    # Update tracking
    prefs.last_digest_sent_at = now
    prefs.total_alerts_sent += len(jobs)
    await db.commit()

    logger.info(
        "Sent job alert digest: user=%s, jobs=%d, provider=%s",
        user_id, len(jobs), provider_name,
    )
    return {"sent": True, "job_count": len(jobs), "provider": provider_name, "error": None}
