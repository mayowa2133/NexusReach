"""Celery tasks: the two waitlist emails that carry a secret link.

* ``send_verification_email`` — double-opt-in confirmation, triggered on join.
* ``send_dashboard_link_email`` — "here's your referral link again" for an
  already-verified member who resubmitted the form.

Both take their token as a task argument because the raw value can't be
recovered from its stored hash. Neither token is ever returned over HTTP: the
email *is* the delivery channel, which is what makes clicking the link evidence
that the recipient owns the address. Fail-soft: when Resend is unconfigured
(dev), the link is logged instead of sent so the flow stays exercisable locally.

Every interpolation into these templates goes through ``html.escape``. ``name``
is attacker-controlled free text from a public, unauthenticated form, and these
messages are sent from our own verified sending domain — an unescaped value
would turn the signup endpoint into a way to mail arbitrary markup, from a
domain recipients trust, to any address the submitter names.
"""

import html
import logging
import uuid

from sqlalchemy import select

from app.clients import resend_client
from app.database import async_session
from app.models.waitlist import WaitlistSignup
from app.services.referral_service import (
    build_dashboard_home_url,
    build_dashboard_url,
    build_verify_url,
    compute_position,
    earned_tier,
)
from app.tasks import celery_app, run_async

logger = logging.getLogger(__name__)


def _greeting(name: str | None) -> str:
    safe_name = html.escape(name or "", quote=False).strip()
    return f"Hi {safe_name}," if safe_name else "Hi,"


def _shell(greeting: str, body: str) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;\
max-width:520px;margin:0 auto;color:#1B1A17;">
  <p style="font-size:16px;line-height:1.5;">{greeting}</p>
{body}
</div>"""


def _link_block(url: str, label: str) -> str:
    # The URL is server-built, but escape it anyway: it lands in an href
    # attribute and in text, and nothing here should depend on a caller's
    # discipline to stay safe.
    safe_url = html.escape(url, quote=True)
    return f"""\
  <p style="margin:28px 0;">
    <a href="{safe_url}"
       style="background:#0C6B4B;color:#fff;text-decoration:none;padding:12px 22px;\
border-radius:6px;font-size:15px;display:inline-block;">
      {label}
    </a>
  </p>
  <p style="font-size:13px;line-height:1.5;color:#6b6b6b;">
    If the button doesn't work, paste this link into your browser:<br>
    <a href="{safe_url}" style="color:#0C6B4B;">{safe_url}</a>
  </p>"""


def _render_verification_email(name: str | None, verify_url: str) -> str:
    return _shell(
        _greeting(name),
        f"""\
  <p style="font-size:16px;line-height:1.5;">
    Thanks for joining the <strong>Solomon</strong> waitlist. Confirm your email
    to lock in your spot — and unlock your personal referral link so you can move
    up the line.
  </p>
{_link_block(verify_url, "Confirm my spot &rarr;")}
  <p style="font-size:13px;line-height:1.5;color:#6b6b6b;">
    Didn't sign up? You can safely ignore this email.
  </p>""",
    )


def _render_referral_credited_email(
    name: str | None, position: int, count: int, dashboard_url: str, unlocked: str | None
) -> str:
    plural = "" if count == 1 else "s"
    reward = (
        f"""
  <p style="font-size:16px;line-height:1.5;">
    That unlocks <strong>{html.escape(unlocked)}</strong>.
  </p>"""
        if unlocked
        else ""
    )
    return _shell(
        _greeting(name),
        f"""\
  <p style="font-size:16px;line-height:1.5;">
    Someone you invited just confirmed their email — so you've moved up the
    <strong>Solomon</strong> waitlist.
  </p>
  <p style="font-size:16px;line-height:1.5;">
    You're now <strong>#{position:,}</strong> in line with
    <strong>{count}</strong> confirmed referral{plural}.
  </p>{reward}
{_link_block(dashboard_url, "See my place in line &rarr;")}
  <p style="font-size:13px;line-height:1.5;color:#6b6b6b;">
    You're getting this because you shared your Solomon referral link.
  </p>""",
    )


def _render_dashboard_link_email(name: str | None, dashboard_url: str) -> str:
    return _shell(
        _greeting(name),
        f"""\
  <p style="font-size:16px;line-height:1.5;">
    You're already on the <strong>Solomon</strong> waitlist — no need to sign up
    twice. Here's your personal referral link and your place in the queue.
  </p>
{_link_block(dashboard_url, "Open my referral dashboard &rarr;")}
  <p style="font-size:13px;line-height:1.5;color:#6b6b6b;">
    Didn't request this? You can safely ignore this email — nothing changed.
  </p>""",
    )


async def _load_signup(db, signup_id: str) -> WaitlistSignup | None:
    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.id == uuid.UUID(signup_id))
    )
    return result.scalar_one_or_none()


async def _run_verification(signup_id: str, verification_token: str) -> dict:
    async with async_session() as db:
        signup = await _load_signup(db, signup_id)
        if signup is None:
            return {"sent": False, "reason": "signup_not_found"}
        if signup.email_verified:
            return {"sent": False, "reason": "already_verified"}

        verify_url = build_verify_url(signup.referral_code, verification_token)
        sent = await resend_client.send_email(
            to=signup.email,
            subject="Confirm your spot on the Solomon waitlist",
            html=_render_verification_email(signup.name, verify_url),
        )
        if not sent:
            # Dev / provider-down: surface the link so verification is testable.
            logger.info("Verification link for %s: %s", signup.email, verify_url)
        return {"sent": sent}


async def _run_dashboard_link(signup_id: str, access_token: str) -> dict:
    async with async_session() as db:
        signup = await _load_signup(db, signup_id)
        if signup is None:
            return {"sent": False, "reason": "signup_not_found"}

        dashboard_url = build_dashboard_url(signup.referral_code, access_token)
        sent = await resend_client.send_email(
            to=signup.email,
            subject="Your Solomon referral link",
            html=_render_dashboard_link_email(signup.name, dashboard_url),
        )
        if not sent:
            logger.info("Dashboard link for %s: %s", signup.email, dashboard_url)
        return {"sent": sent}


async def _run_referral_credited(referrer_id: str) -> dict:
    async with async_session() as db:
        referrer = await _load_signup(db, referrer_id)
        if referrer is None:
            return {"sent": False, "reason": "referrer_not_found"}
        # Only mail an address that has been confirmed. An unverified referrer
        # never proved they own it, and this is unsolicited (they didn't ask for
        # it) — sending would risk mailing a stranger and hurt our domain's
        # reputation. They still get credited; they just hear about it on the
        # dashboard after confirming.
        if not referrer.email_verified:
            return {"sent": False, "reason": "referrer_unverified"}

        count = referrer.verified_referral_count
        position = await compute_position(db, referrer)

        # Name a newly-crossed threshold without duplicating the reward copy that
        # lives in the frontend's ladder — otherwise the two drift.
        tier = earned_tier(count)
        unlocked = (
            f"a new reward at {tier} referral{'' if tier == 1 else 's'}"
            if tier and tier != earned_tier(count - 1)
            else None
        )

        dashboard_url = build_dashboard_home_url(referrer.referral_code)
        sent = await resend_client.send_email(
            to=referrer.email,
            subject="You moved up the Solomon waitlist",
            html=_render_referral_credited_email(
                referrer.name, position, count, dashboard_url, unlocked
            ),
        )
        if not sent:
            logger.info(
                "Referral-credited notice for %s: #%s (%s referrals)",
                referrer.email,
                position,
                count,
            )
        return {"sent": sent, "position": position, "count": count}


@celery_app.task(
    name="app.tasks.referrals.send_verification_email",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def send_verification_email(signup_id: str, verification_token: str) -> dict:
    """Send (or log) the double-opt-in email for a waitlist signup."""
    result = run_async(_run_verification(signup_id, verification_token))
    logger.info("Verification email task complete: %s", result)
    return result


@celery_app.task(
    name="app.tasks.referrals.send_dashboard_link_email",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def send_dashboard_link_email(signup_id: str, access_token: str) -> dict:
    """Re-send a verified member's referral dashboard link to their mailbox."""
    result = run_async(_run_dashboard_link(signup_id, access_token))
    logger.info("Dashboard link email task complete: %s", result)
    return result


@celery_app.task(
    name="app.tasks.referrals.send_referral_credited_email",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=3,
)
def send_referral_credited_email(referrer_id: str) -> dict:
    """Tell a referrer that an invitee confirmed and they moved up.

    This is the loop's flywheel: without it a referrer only learns their share
    worked by revisiting the dashboard, so nothing prompts the *next* share.
    Fired only from the confirmation that actually incremented their tally, so a
    replayed verify link can't re-notify.
    """
    result = run_async(_run_referral_credited(referrer_id))
    logger.info("Referral credited email task complete: %s", result)
    return result
