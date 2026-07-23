"""Public pre-launch waitlist capture + token-gated admin export.

``POST /api/waitlist`` is unauthenticated (prospective users have no account)
and rate-limited by IP. On join it mints the referral primitives, queues a
double-opt-in verification email, and returns the referral status so the
frontend can show the "refer your friends" panel. ``GET /api/waitlist`` is
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
from app.services import referral_service
from app.services.waitlist_service import (
    list_waitlist_signups,
    upsert_waitlist_signup,
)
from app.tasks.referrals import send_verification_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.post("", response_model=WaitlistSignupResponse)
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

    client_ip = request.client.host if request.client else None
    await referral_service.enforce_signup_ip_limit(client_ip)

    entry, already, access_token = await upsert_waitlist_signup(
        db, payload, signup_ip=client_ip
    )

    # Send (or, in dev, log) the verification email for anyone not yet verified.
    if not entry.email_verified:
        try:
            send_verification_email.delay(str(entry.id), access_token)
        except Exception:  # broker down must never break the signup
            logger.warning("Could not queue verification email", exc_info=True)

    # Best-effort mirror to the Google Sheet (after the response, never blocking).
    if sheets_mirror_client.is_configured():
        background_tasks.add_task(
            sheets_mirror_client.mirror_signup,
            {
                "name": entry.name,
                "email": entry.email,
                "linkedin_url": entry.linkedin_url,
                "current_title": entry.current_title,
                "target_role": entry.target_role,
                "note": entry.note,
                "source": entry.source,
                "referral_code": entry.referral_code,
                "referred_by_id": (
                    str(entry.referred_by_id) if entry.referred_by_id else None
                ),
                "email_verified": entry.email_verified,
                "already_on_list": already,
            },
        )

    payload_out = await referral_service.referral_status_payload(db, entry)
    return WaitlistSignupResponse(
        ok=True,
        already_on_list=already,
        access_token=access_token,
        name=entry.name,
        **payload_out,
    )


@router.get("", response_model=WaitlistExportResponse)
async def export_waitlist(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> WaitlistExportResponse:
    """Export all waitlist entries. Requires the admin token header.

    Returns 404 when no admin token is configured so the endpoint's existence
    isn't advertised, and 403 on a token mismatch.
    """
    configured = settings.waitlist_admin_token
    if not configured:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not x_admin_token or not hmac.compare_digest(x_admin_token, configured):
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
                note=r.note,
                source=r.source,
                invited=r.invited,
                created_at=r.created_at.isoformat(),
                referral_code=r.referral_code,
                referred_by_id=str(r.referred_by_id) if r.referred_by_id else None,
                email_verified=r.email_verified,
                verified_referral_count=r.verified_referral_count,
                earned_tier=referral_service.earned_tier(r.verified_referral_count),
            )
            for r in rows
        ],
    )
