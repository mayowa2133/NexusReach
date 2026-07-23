"""Public referral endpoints for the pre-launch waitlist.

Both endpoints are unauthenticated but token-guarded: the caller must present a
signup's PUBLIC ``code`` together with its SECRET access token ``t`` (only the
owner has it, from the join response or the verification email). No account /
JWT is involved — waitlist signups have none.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.waitlist import ReferralStatus
from app.services import referral_service

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


@router.get("/verify", response_model=ReferralStatus)
@limiter.limit("30/minute")
async def verify_referral(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str, Query(max_length=16)],
    t: Annotated[str, Query(max_length=128)],
) -> ReferralStatus:
    """Confirm an email (idempotent) and credit the referrer; returns status."""
    signup = await referral_service.verify_signup(db, code, t)
    if signup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    payload = await referral_service.referral_status_payload(db, signup)
    return ReferralStatus(name=signup.name, **payload)
