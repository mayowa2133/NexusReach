"""Public pre-launch waitlist capture + token-gated admin export.

``POST /api/waitlist`` is unauthenticated (prospective users have no account)
and rate-limited by IP. On a new join it queues a mailbox-verification email.
Every accepted submission receives the same acknowledgement; credentials and
signup state are never returned to an anonymous caller.
``GET /api/waitlist`` is
guarded by a shared-secret header so the owner can export entries at launch; it
is disabled entirely unless ``NEXUSREACH_WAITLIST_ADMIN_TOKEN`` is configured.
"""

import hmac
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import sheets_mirror_client
from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.waitlist import (
    WaitlistEntry,
    WaitlistExportResponse,
    WaitlistSignupCreate,
    WaitlistSignupResponse,
)
from app.services import referral_service, waitlist_resume_service
from app.services.waitlist_service import (
    list_waitlist_signups,
    upsert_waitlist_signup,
)
from app.tasks.referrals import send_verification_email
from app.tasks.waitlist_resume import parse_waitlist_resume
from app.utils.client_ip import client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.post("", response_model=WaitlistSignupResponse, status_code=202)
@limiter.limit("10/minute")
async def join_waitlist(
    request: Request,
    payload: WaitlistSignupCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> WaitlistSignupResponse:
    """Capture a landing-page waitlist submission (idempotent per email)."""
    email = str(payload.email).strip().lower()
    if referral_service.is_disposable_email(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please use a permanent email address.",
        )

    # Validate any attached resume BEFORE creating the signup: invalid input is
    # the visitor's to fix, so tell them rather than silently dropping the file.
    resume = waitlist_resume_service.decode_and_validate(payload)

    # Resolved through the proxy chain — the socket peer is the edge, so keying
    # the daily cap on it would make it a site-wide ceiling instead of per-IP.
    caller_ip = client_ip(request)
    await referral_service.enforce_signup_ip_limit(caller_ip)

    result = await upsert_waitlist_signup(db, payload, signup_ip=caller_ip)
    entry, already = result.entry, result.already_on_list

    # Store the file (fail-soft) and queue the out-of-band parse — for a NEW
    # signup only. Attaching to an existing row would let anyone who knows an
    # address replace that person's stored resume: the object path is derived
    # from the row id and uploads are `x-upsert`, so it overwrites in place. The
    # file is still validated above, so the response is identical either way and
    # a returning visitor with a bad file is told about it.
    if resume is not None and not already:
        resume_bytes, resume_content_type = resume
        await waitlist_resume_service.attach_resume(
            entry, resume_bytes, resume_content_type, payload.resume_filename
        )
        await db.commit()
        if entry.resume_path:
            try:
                parse_waitlist_resume.delay(str(entry.id))
            except Exception:  # broker down must never break the signup
                logger.warning("Could not queue resume parse", exc_info=True)

    # The single-use exchange credential is delivered only to the mailbox. An
    # existing signup is deliberately a no-op; recovery is a separate endpoint
    # with recipient and global throttles.
    try:
        if result.verification_token is not None:
            send_verification_email.delay(str(entry.id), result.verification_token)
    except Exception:  # broker down must never break the signup
        logger.warning("Could not queue waitlist email", exc_info=True)

    # Best-effort mirror to the Google Sheet (after the response, never blocking).
    if sheets_mirror_client.is_configured() and not already:
        background_tasks.add_task(
            sheets_mirror_client.mirror_signup,
            {
                "name": entry.name,
                "email": entry.email,
                "linkedin_url": entry.linkedin_url,
                "current_title": entry.current_title,
                "target_role": entry.target_role,
                "target_occupation": entry.target_occupation,
                "note": entry.note,
                "source": entry.source,
                "referral_code": entry.referral_code,
                "referred_by_id": (
                    str(entry.referred_by_id) if entry.referred_by_id else None
                ),
                "email_verified": entry.email_verified,
                "already_on_list": already,
                "goals": ", ".join(entry.goals or []),
                # Flag only — never the file bytes (Apps Script has a 10s timeout).
                "has_resume": bool(entry.resume_path),
            },
        )

    return WaitlistSignupResponse(ok=True)


@router.get("", response_model=WaitlistExportResponse)
@limiter.limit("5/minute")
async def export_waitlist(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> WaitlistExportResponse:
    """Export all waitlist entries. Requires the admin token header.

    Returns 404 when no admin token is configured so the endpoint's existence
    isn't advertised, and 403 on a token mismatch.

    Rate-limited because this returns the entire list — every email, LinkedIn
    URL, note and resume filename — behind a single shared secret. Without a
    limit that secret can be guessed at full request rate; 5/minute makes an
    online search hopeless while staying far above any real export need. The
    comparison is constant-time, and production additionally requires the token
    to be long enough to be worth comparing (see config validation).
    """
    configured = settings.waitlist_admin_token
    if not configured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not x_admin_token or not hmac.compare_digest(x_admin_token, configured):
        # Logged so repeated guessing is visible in the API logs rather than silent.
        logger.warning(
            "Rejected waitlist export attempt from %s", client_ip(request)
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin token"
        )

    rows = await list_waitlist_signups(db)
    return WaitlistExportResponse(
        count=len(rows),
        entries=[
            WaitlistEntry(
                id=str(r.id),
                email=r.email,
                name=r.name,
                linkedin_url=r.linkedin_url,
                current_title=r.current_title,
                target_role=r.target_role,
                target_occupation=r.target_occupation,
                note=r.note,
                source=r.source,
                invited=r.invited,
                created_at=r.created_at.isoformat(),
                referral_code=r.referral_code,
                referred_by_id=str(r.referred_by_id) if r.referred_by_id else None,
                email_verified=r.email_verified,
                verified_referral_count=r.verified_referral_count,
                earned_tier=referral_service.earned_tier(r.verified_referral_count),
                goals=r.goals,
                has_resume=bool(r.resume_path),
                resume_filename=r.resume_filename,
                resume_parse_status=r.resume_parse_status,
            )
            for r in rows
        ],
    )
