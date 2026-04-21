"""Weekly cadence digest — sends a summary of pending next actions to the user.

Runs via Celery beat every Monday at 09:00 UTC. Only fires when:
  - user has cadence_digest_enabled = True
  - user has at least one email provider connected (Gmail or Outlook)
  - no digest sent in the last 6 days (guards against duplicate fires)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import UserSettings
from app.models.user import User
from app.services.cadence_service import NextAction, compute_next_actions

logger = logging.getLogger(__name__)

URGENCY_LABEL = {"high": "🔴 High", "medium": "🟡 Medium", "low": "🟢 Low"}
KIND_LABEL = {
    "reply_needed": "Reply needed",
    "thank_you_due": "Thank-you due",
    "draft_unsent": "Unsent draft",
    "awaiting_reply": "Awaiting reply",
    "live_targets_unused": "Research unused",
    "applied_untouched": "Applied — no outreach",
}

# Don't resend if last digest was within this many days
MIN_DAYS_BETWEEN_DIGESTS = 6


# ---------------------------------------------------------------------------
# HTML / text rendering
# ---------------------------------------------------------------------------


def _render_html(actions: list[NextAction], user_email: str) -> str:
    high = [a for a in actions if a.urgency == "high"]
    medium = [a for a in actions if a.urgency == "medium"]
    low = [a for a in actions if a.urgency == "low"]

    def _section(title: str, color: str, items: list[NextAction]) -> str:
        if not items:
            return ""
        rows = []
        for a in items:
            kind = KIND_LABEL.get(a.kind, a.kind)
            who = a.person_name or a.company_name or ""
            job = a.job_title or ""
            label = f"{who} — {job}" if who and job else who or job or "—"
            age = f"{a.age_days:.0f}d ago" if a.age_days is not None else ""
            rows.append(
                f'<tr style="border-bottom:1px solid #f3f4f6">'
                f'<td style="padding:8px 12px;font-weight:500">{kind}</td>'
                f'<td style="padding:8px 12px;color:#374151">{label}</td>'
                f'<td style="padding:8px 4px;color:#6b7280;font-size:12px">{age}</td>'
                f'<td style="padding:8px 12px;color:#6b7280;font-size:12px">{a.reason}</td>'
                f'</tr>'
            )
        return (
            f'<h3 style="margin:20px 0 6px;color:{color}">{title}</h3>'
            f'<table style="width:100%;border-collapse:collapse;font-size:14px">'
            f'<tbody>{"".join(rows)}</tbody></table>'
        )

    body = (
        _section("🔴 High priority", "#dc2626", high)
        + _section("🟡 Medium priority", "#d97706", medium)
        + _section("🟢 Low priority", "#16a34a", low)
    )

    total = len(actions)
    return f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:640px;margin:0 auto;padding:24px">
  <h2 style="color:#111827;margin-bottom:4px">Your weekly outreach digest</h2>
  <p style="color:#6b7280;margin-top:0">{total} item{'s' if total != 1 else ''} need your attention this week.</p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0">
  {body}
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 12px">
  <p style="color:#9ca3af;font-size:12px;margin:0">
    Sent by NexusReach weekly cadence digest. Turn off in Settings → Cadence Thresholds.
  </p>
</div>
"""


def _render_text(actions: list[NextAction]) -> str:
    lines = [f"Your weekly outreach digest — {len(actions)} item(s)\n"]
    for urgency in ("high", "medium", "low"):
        group = [a for a in actions if a.urgency == urgency]
        if not group:
            continue
        lines.append(f"\n[{urgency.upper()}]")
        for a in group:
            kind = KIND_LABEL.get(a.kind, a.kind)
            who = a.person_name or a.company_name or ""
            age = f" ({a.age_days:.0f}d)" if a.age_days is not None else ""
            lines.append(f"  • {kind}: {who}{age} — {a.reason}")
    lines.append("\n---\nManage digest in Settings → Cadence Thresholds.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Send helpers (delegate to job_alert_service providers)
# ---------------------------------------------------------------------------


async def _send(
    user_settings: UserSettings,
    user_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> str:
    """Send via whichever provider is connected. Returns provider name."""
    from app.services.job_alert_service import _send_via_gmail, _send_via_outlook  # noqa: PLC0415

    if user_settings.gmail_connected and user_settings.gmail_refresh_token:
        await _send_via_gmail(user_settings, user_email, subject, html_body, text_body)
        return "gmail"
    if user_settings.outlook_connected and user_settings.outlook_refresh_token:
        await _send_via_outlook(user_settings, user_email, subject, html_body)
        return "outlook"
    raise ValueError("No email provider connected")


# ---------------------------------------------------------------------------
# Per-user orchestration
# ---------------------------------------------------------------------------


async def send_cadence_digest_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Compute next actions and send digest. Returns status dict."""
    # Load settings
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    user_settings = result.scalar_one_or_none()

    if not user_settings:
        return {"sent": False, "error": "no_settings"}
    if not user_settings.cadence_digest_enabled:
        return {"sent": False, "error": "digest_disabled"}
    if not (user_settings.gmail_connected or user_settings.outlook_connected):
        return {"sent": False, "error": "no_email_provider"}

    # Guard: skip if sent recently
    now = datetime.now(timezone.utc)
    if user_settings.cadence_digest_last_sent_at:
        last = user_settings.cadence_digest_last_sent_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last).days < MIN_DAYS_BETWEEN_DIGESTS:
            return {"sent": False, "error": "too_soon"}

    # Compute actions
    actions = await compute_next_actions(db, user_id)
    if not actions:
        return {"sent": False, "error": None, "action_count": 0}

    # Get user email
    user_stmt = select(User.email).where(User.id == user_id)
    user_result = await db.execute(user_stmt)
    user_email = user_result.scalar_one_or_none()
    if not user_email:
        return {"sent": False, "error": "no_user_email"}

    subject = f"NexusReach: {len(actions)} outreach action{'s' if len(actions) != 1 else ''} this week"
    html_body = _render_html(actions, user_email)
    text_body = _render_text(actions)

    try:
        provider = await _send(user_settings, user_email, subject, html_body, text_body)
    except Exception:
        logger.exception("Cadence digest send failed for user %s", user_id)
        return {"sent": False, "error": "send_failed", "action_count": len(actions)}

    user_settings.cadence_digest_last_sent_at = now
    await db.commit()

    logger.info(
        "Sent cadence digest: user=%s actions=%d provider=%s",
        user_id, len(actions), provider,
    )
    return {"sent": True, "action_count": len(actions), "provider": provider, "error": None}


# ---------------------------------------------------------------------------
# Fan-out: all eligible users
# ---------------------------------------------------------------------------


async def send_all_cadence_digests(db: AsyncSession) -> dict:
    """Send weekly cadence digest to all eligible users."""
    stmt = select(UserSettings.user_id).where(
        UserSettings.cadence_digest_enabled == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    user_ids = [row[0] for row in result.all()]

    logger.info("Cadence digest: %d users with digest enabled", len(user_ids))

    sent = 0
    skipped = 0
    failed = 0

    for uid in user_ids:
        try:
            from app.database import async_session  # noqa: PLC0415

            async with async_session() as session:
                status = await send_cadence_digest_for_user(session, uid)
            if status["sent"]:
                sent += 1
            elif status.get("error") in ("send_failed",):
                failed += 1
            else:
                skipped += 1
        except Exception:
            logger.exception("Cadence digest error for user %s", uid)
            failed += 1

    return {"users_checked": len(user_ids), "sent": sent, "skipped": skipped, "failed": failed}
