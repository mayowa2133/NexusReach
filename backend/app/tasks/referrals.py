"""Celery task: send the waitlist double-opt-in verification email.

Triggered ``.delay(signup_id, access_token)`` from the join handler. The raw
access token can't be recovered from its stored hash, so it rides through the
broker as a task arg to build the one-click verify link. Fail-soft: when Resend
is unconfigured (dev), the verification link is logged instead of sent so the
flow is still exercisable locally.
"""

import logging
import uuid

from sqlalchemy import select

from app.clients import resend_client
from app.database import async_session
from app.models.waitlist import WaitlistSignup
from app.services.referral_service import build_verify_url
from app.tasks import celery_app, run_async

logger = logging.getLogger(__name__)


def _render_email(name: str, verify_url: str) -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;\
max-width:520px;margin:0 auto;color:#1B1A17;">
  <p style="font-size:16px;line-height:1.5;">{greeting}</p>
  <p style="font-size:16px;line-height:1.5;">
    Thanks for joining the <strong>Solomon</strong> waitlist. Confirm your email
    to lock in your spot — and unlock your personal referral link so you can move
    up the line.
  </p>
  <p style="margin:28px 0;">
    <a href="{verify_url}"
       style="background:#0C6B4B;color:#fff;text-decoration:none;padding:12px 22px;\
border-radius:6px;font-size:15px;display:inline-block;">
      Confirm my spot &rarr;
    </a>
  </p>
  <p style="font-size:13px;line-height:1.5;color:#6b6b6b;">
    If the button doesn't work, paste this link into your browser:<br>
    <a href="{verify_url}" style="color:#0C6B4B;">{verify_url}</a>
  </p>
  <p style="font-size:13px;line-height:1.5;color:#6b6b6b;">
    Didn't sign up? You can safely ignore this email.
  </p>
</div>"""


async def _run(signup_id: str, access_token: str) -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(WaitlistSignup).where(WaitlistSignup.id == uuid.UUID(signup_id))
        )
        signup = result.scalar_one_or_none()
        if signup is None:
            return {"sent": False, "reason": "signup_not_found"}
        if signup.email_verified:
            return {"sent": False, "reason": "already_verified"}

        verify_url = build_verify_url(signup.referral_code, access_token)
        sent = await resend_client.send_email(
            to=signup.email,
            subject="Confirm your spot on the Solomon waitlist",
            html=_render_email(signup.name, verify_url),
        )
        if not sent:
            # Dev / provider-down: surface the link so verification is testable.
            logger.info("Verification link for %s: %s", signup.email, verify_url)
        return {"sent": sent}


@celery_app.task(
    name="app.tasks.referrals.send_verification_email",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def send_verification_email(signup_id: str, access_token: str) -> dict:
    """Send (or log) the verification email for a waitlist signup."""
    result = run_async(_run(signup_id, access_token))
    logger.info("Verification email task complete: %s", result)
    return result
