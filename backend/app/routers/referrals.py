"""Public referral endpoints for the pre-launch waitlist.

Both endpoints are unauthenticated but token-guarded, and they take *different*
secrets on purpose. ``/status`` needs the PUBLIC ``code`` plus the dashboard
access token ``t``. ``/verify`` needs the ``code`` plus the single-use
confirmation token ``v``, which exists only inside the email we sent — that is
what makes confirming an address evidence of mailbox control rather than a
formality any form submitter could complete. No account / JWT is involved —
waitlist signups have none.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.waitlist import (
    ReferralStatus,
    ReferralVerifyResponse,
    WaitlistDeleteResponse,
)
from app.services import referral_service, waitlist_retention_service

router = APIRouter(prefix="/referrals", tags=["referrals"])


@router.get("/status", response_model=ReferralStatus)
@limiter.limit("30/minute")
async def referral_status(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str, Query(max_length=16)],
    t: Annotated[str, Query(max_length=128)],
) -> ReferralStatus:
    """Live referral status for the owner's dashboard (position, tier, link)."""
    signup = await referral_service.resolve_signup_by_token(db, code, t)
    if signup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    payload = await referral_service.referral_status_payload(db, signup)
    return ReferralStatus(name=signup.name, **payload)


@router.get("/verify", response_model=ReferralVerifyResponse)
@limiter.limit("30/minute")
async def verify_referral(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str, Query(max_length=16)],
    v: Annotated[str, Query(max_length=128)],
) -> ReferralVerifyResponse:
    """Confirm an email, credit the referrer, and hand back a dashboard key.

    ``v`` is the single-use token from the confirmation email and is consumed
    here; the returned ``access_token`` is what the page keeps for subsequent
    ``/status`` reads. A replayed link 404s — by then the browser already holds
    the access token from the first click.
    """
    verified = await referral_service.verify_signup(db, code, v)
    if verified is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    signup, access_token = verified
    payload = await referral_service.referral_status_payload(db, signup)
    return ReferralVerifyResponse(
        name=signup.name, access_token=access_token, **payload
    )


@router.delete("/me", response_model=WaitlistDeleteResponse)
@limiter.limit("10/minute")
async def delete_my_waitlist_data(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str, Query(max_length=16)],
    t: Annotated[str, Query(max_length=128)],
) -> WaitlistDeleteResponse:
    """Erase this waitlist signup and its stored resume.

    Waitlist members have no account, so ``/api/account/delete`` cannot reach
    them — this is their only way out, authenticated by the same owner token
    that reads the dashboard. Removes the Storage object alongside the row so
    erasure never leaves an orphaned file in the bucket.

    Idempotent from the caller's side: once the row is gone the token no longer
    resolves and a repeat call 404s.
    """
    signup = await referral_service.resolve_signup_by_token(db, code, t)
    if signup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    result = await waitlist_retention_service.delete_signup(db, signup)
    return WaitlistDeleteResponse(**result)
