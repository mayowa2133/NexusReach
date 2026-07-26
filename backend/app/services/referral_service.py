"""Referral-loop primitives for the pre-launch waitlist.

Splits cleanly into three concerns, all pure/DB helpers reused by the waitlist
service, the referrals router, and the verification Celery task:

* **codes + tokens** — a PUBLIC shareable ``referral_code`` plus two SECRET,
  hash-at-rest tokens (the ``companion_tokens`` pattern: plaintext handed over
  once, only the SHA-256 hash stored). ``access_token`` (``nrw_``) authorizes
  dashboard *reads*; ``verification_token`` (``nrv_``) authorizes the one-click
  email confirmation and is single-use. They are deliberately distinct: the
  verification token is delivered ONLY by email, so confirming an address proves
  mailbox control. Collapsing them — or returning the verification token from
  an HTTP endpoint — turns double-opt-in into a formality and lets a referrer
  self-verify unlimited invented invitees.
* **anti-fraud** — disposable-domain blocking, self-referral detection via a
  normalized fraud key, and a per-IP daily signup cap (reusing the sliding
  window from ``discovery_rate_limit``).
* **status** — queue position (referral-count ranked), verified total, and the
  earned reward tier — composed once in :func:`referral_status_payload` so the
  join response, the dashboard, and the verify endpoint never drift.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.waitlist import WaitlistSignup
from app.utils.discovery_rate_limit import _enforce_daily_limit

ACCESS_TOKEN_PREFIX = "nrw_"
VERIFICATION_TOKEN_PREFIX = "nrv_"

# Unambiguous base32-ish alphabet (no I/L/O/0/1). MUST match migration 061's
# ``_CODE_ALPHABET`` so backfilled and live codes share one format.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 10

_DISPOSABLE_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "disposable_email_domains.txt"
)


# --- Codes + tokens -------------------------------------------------------

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_access_token() -> str:
    """A fresh secret owner token (plaintext; store only its hash)."""
    return ACCESS_TOKEN_PREFIX + secrets.token_urlsafe(32)


def mint_verification_token() -> str:
    """A fresh single-use email-confirmation token.

    Only ever leaves the server inside an email. Callers must not put it in an
    HTTP response body, a log line, or a redirect target.
    """
    return VERIFICATION_TOKEN_PREFIX + secrets.token_urlsafe(32)


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


async def mint_unique_referral_code(db: AsyncSession) -> str:
    """Generate a referral code not already used (retry on the rare collision)."""
    for _ in range(10):
        code = _generate_code()
        exists = await db.execute(
            select(WaitlistSignup.id).where(WaitlistSignup.referral_code == code)
        )
        if exists.scalar_one_or_none() is None:
            return code
    # Astronomically unlikely with a 30^10 space; widen rather than loop forever.
    return _generate_code() + secrets.choice(_CODE_ALPHABET)


# --- Anti-fraud -----------------------------------------------------------

@lru_cache(maxsize=1)
def _disposable_domains() -> frozenset[str]:
    domains: set[str] = set()
    try:
        for line in _DISPOSABLE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                domains.add(line)
    except OSError:
        return frozenset()
    return frozenset(domains)


def is_disposable_email(email: str) -> bool:
    """True when the email's domain is a known throwaway provider."""
    domain = email.strip().lower().rpartition("@")[2]
    return domain in _disposable_domains()


def fraud_key(email: str) -> str:
    """Normalize an email for duplicate/self-referral comparison only.

    Collapses Gmail dots and any ``+tag`` so ``me+1@gmail.com`` and
    ``m.e@gmail.com`` map to the same key. Used ONLY for fraud comparisons —
    the stored/queried email stays the plain lowercased address.
    """
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    local = local.split("+", 1)[0]
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.replace(".", "")
    return f"{local}@{domain}"


async def enforce_signup_ip_limit(ip: str | None) -> None:
    """Per-IP daily signup ceiling (raises HTTPException 429 when exceeded)."""
    if not ip:
        return
    await _enforce_daily_limit(
        f"nexusreach:referral_signup_ip:{ip}",
        settings.referral_signup_ip_daily_limit,
        "Too many signups from this network today. Please try again tomorrow.",
    )


async def resolve_referrer(
    db: AsyncSession, code: str | None, signup_email: str
) -> WaitlistSignup | None:
    """Return the referrer for ``code``, rejecting self-referral.

    ``None`` when the code is unknown/blank or resolves to the same person (by
    normalized fraud key) — attribution is simply dropped rather than erroring.
    """
    if not code:
        return None
    result = await db.execute(
        select(WaitlistSignup).where(WaitlistSignup.referral_code == code.strip())
    )
    referrer = result.scalar_one_or_none()
    if referrer is None:
        return None
    if fraud_key(referrer.email) == fraud_key(signup_email):
        return None
    return referrer


# --- Token resolution + verification -------------------------------------

async def resolve_signup_by_token(
    db: AsyncSession, code: str, token: str
) -> WaitlistSignup | None:
    """Return the signup owning ``(code, access_token)``, else ``None``.

    Read-only authorization for the referral dashboard. This token deliberately
    does NOT authorize verification — see :func:`verify_signup`.
    """
    if not token or not token.startswith(ACCESS_TOKEN_PREFIX):
        return None
    result = await db.execute(
        select(WaitlistSignup).where(
            WaitlistSignup.referral_code == code,
            WaitlistSignup.access_token_hash == hash_token(token),
        )
    )
    return result.scalar_one_or_none()


def issue_access_token(signup: WaitlistSignup) -> str:
    """Stamp a fresh dashboard key on ``signup``, returning the plaintext once.

    Only stores the hash; the caller owns the commit. Hand the plaintext only to
    someone who has proved they own the address — the mailbox (a verification
    click or an emailed link), or the browser that just created a brand-new row.
    """
    token = mint_access_token()
    signup.access_token_hash = hash_token(token)
    return token


def issue_verification_token(signup: WaitlistSignup) -> str:
    """Stamp a fresh single-use confirmation key on ``signup``.

    The plaintext is for the outbound email and nothing else.
    """
    token = mint_verification_token()
    signup.verification_token_hash = hash_token(token)
    return token


async def verify_signup(
    db: AsyncSession, code: str, token: str
) -> tuple[WaitlistSignup, str] | None:
    """Confirm an email, credit the referrer, and return a dashboard key.

    ``token`` must be the emailed ``nrv_`` verification token — the dashboard
    ``nrw_`` access token is rejected, which is what keeps a referral countable
    only by someone who can read the invitee's mail.

    Returns ``(signup, access_token)`` on success, ``None`` when the code/token
    doesn't resolve. The verification token is consumed (cleared) on first use
    and the referrer is credited exactly once, in the same transaction, so a
    re-clicked link can never double-count. Because the token is single-use, a
    second click no longer resolves; the caller renders that as an expired link
    and the visitor still has the dashboard key from the first click.
    """
    if not token or not token.startswith(VERIFICATION_TOKEN_PREFIX):
        return None
    result = await db.execute(
        select(WaitlistSignup).where(
            WaitlistSignup.referral_code == code,
            WaitlistSignup.verification_token_hash == hash_token(token),
        )
    )
    signup = result.scalar_one_or_none()
    if signup is None:
        return None

    # Consume the single-use token whether or not this is the first confirmation.
    signup.verification_token_hash = None
    access_token = issue_access_token(signup)

    if not signup.email_verified:
        signup.email_verified = True
        signup.verified_at = datetime.now(timezone.utc)

        if signup.referred_by_id is not None:
            await db.execute(
                WaitlistSignup.__table__.update()
                .where(WaitlistSignup.id == signup.referred_by_id)
                .values(
                    verified_referral_count=WaitlistSignup.verified_referral_count + 1
                )
            )

    await db.commit()
    await db.refresh(signup)
    return signup, access_token


# --- Status: position, total, tier ---------------------------------------

def tier_thresholds() -> list[int]:
    """Sorted verified-referral thresholds that unlock reward-ladder rungs."""
    out: set[int] = set()
    for part in settings.referral_tier_thresholds.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return sorted(out)


def earned_tier(verified_referral_count: int) -> int:
    """Highest threshold reached (0 when none) for a verified-referral count."""
    reached = [t for t in tier_thresholds() if verified_referral_count >= t]
    return max(reached) if reached else 0


def _base_url() -> str:
    return (settings.referral_public_base_url or settings.frontend_url).rstrip("/")


def build_share_url(code: str) -> str:
    """The public link a referrer shares (lands on the waitlist with ?ref=)."""
    return f"{_base_url()}/?ref={code}"


def build_dashboard_url(code: str, access_token: str) -> str:
    """The owner-only referral dashboard link (email delivery only)."""
    return f"{_base_url()}/r/{code}?t={access_token}"


def build_verify_url(code: str, verification_token: str) -> str:
    """The one-click email-confirmation link (lands on the dashboard).

    Carries the single-use ``nrv_`` token under ``v``; the page exchanges it for
    a dashboard key. Distinct from ``t`` so the two secrets never get confused
    at either end.
    """
    return f"{_base_url()}/r/{code}?v={verification_token}"


async def compute_position(db: AsyncSession, signup: WaitlistSignup) -> int:
    """Queue position ranked by verified referrals, then signup time.

    ``1 + (# rows strictly ahead)``: more verified referrals win; ties break to
    the earlier signup. Referring moves you ahead of everyone with fewer invites.
    """
    result = await db.execute(
        select(func.count())
        .select_from(WaitlistSignup)
        .where(
            or_(
                WaitlistSignup.verified_referral_count
                > signup.verified_referral_count,
                and_(
                    WaitlistSignup.verified_referral_count
                    == signup.verified_referral_count,
                    WaitlistSignup.created_at < signup.created_at,
                ),
            )
        )
    )
    return int(result.scalar_one()) + 1


async def count_verified(db: AsyncSession) -> int:
    """Total verified members — the denominator for the launch goal."""
    result = await db.execute(
        select(func.count())
        .select_from(WaitlistSignup)
        .where(WaitlistSignup.email_verified.is_(True))
    )
    return int(result.scalar_one())


async def referral_status_payload(
    db: AsyncSession, signup: WaitlistSignup
) -> dict:
    """Single source of truth for the referral status shown everywhere."""
    position = await compute_position(db, signup)
    total_verified = await count_verified(db)
    return {
        "referral_code": signup.referral_code,
        "position": position,
        "total_verified": total_verified,
        "launch_target": settings.referral_launch_target,
        "share_url": build_share_url(signup.referral_code),
        "email_verified": signup.email_verified,
        "verified_referral_count": signup.verified_referral_count,
        "earned_tier": earned_tier(signup.verified_referral_count),
        "tier_thresholds": tier_thresholds(),
    }
