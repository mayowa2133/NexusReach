"""Resend transactional email client.

The referral waitlist needs to send double-opt-in verification emails, but
waitlist signups have no OAuth mailbox (unlike the Gmail/Microsoft Graph
user-send paths in ``gmail_service`` / ``outlook_service``). This is the only
system/transactional email path in the backend.

Fail-soft by design: when ``NEXUSREACH_RESEND_API_KEY`` /
``NEXUSREACH_RESEND_FROM_EMAIL`` are unset (local dev), we skip the network call
and return ``False`` so the caller can log delivery failure. The signup itself
has already succeeded, so email is always best-effort.
"""

import logging

import httpx

from app.config import settings
from app.utils.resource_limits import consume, identity_key

logger = logging.getLogger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"
_TIMEOUT_SECONDS = 15.0


def is_configured() -> bool:
    """True when a Resend key + verified sender are both set."""
    return bool(settings.resend_api_key and settings.resend_from_email)


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    idempotency_key: str | None = None,
) -> bool:
    """Send a transactional email via Resend.

    Returns ``True`` only when Resend accepted the message. Returns ``False``
    (never raises) when unconfigured or on any provider/network error, so a
    flaky email provider can never break a waitlist signup.
    """
    if not is_configured():
        logger.info("Resend not configured; transactional email skipped")
        return False

    from app.utils.email_identity import canonical_mailbox
    recipient = identity_key(canonical_mailbox(to))
    recipient_limit = settings.system_email_recipient_daily_limit
    if to.strip().lower() == settings.waitlist_notify_email.strip().lower():
        recipient_limit = settings.system_email_daily_limit
    try:
        await consume([
            ("system-email", settings.system_email_daily_limit, 1),
            (f"system-email-recipient:{recipient}", recipient_limit, 1),
        ])
    except Exception:
        logger.warning("Transactional email admission refused or unavailable")
        return False

    payload: dict[str, object] = {
        "from": settings.resend_from_email,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            headers = {"Authorization": f"Bearer {settings.resend_api_key}"}
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key
            resp = await client.post(
                _RESEND_API_URL,
                json=payload,
                headers=headers,
            )
        if resp.status_code >= 400:
            logger.error(
                "Resend send failed (%s): %s",
                resp.status_code,
                resp.text[:500],
            )
            return False
        return True
    except httpx.HTTPError:
        logger.error("Resend send errored", exc_info=True)
        return False
