"""Mailbox-proven referral access and generic public recovery."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.waitlist import (
    ReferralStatus,
    ReferralVerifyResponse,
    WaitlistDeleteResponse,
)
from app.services import referral_service, waitlist_retention_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/referrals", tags=["referrals"])
owner_bearer = HTTPBearer(auto_error=False)


class ReferralExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    token: str = Field(min_length=8, max_length=128)


class ReferralRecoveryRequest(BaseModel):
    email: EmailStr


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return credentials.credentials


@router.get("/status", response_model=ReferralStatus)
@limiter.limit("30/minute")
async def referral_status(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str, Query(max_length=16)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(owner_bearer)
    ],
) -> ReferralStatus:
    """Live referral status for the owner's dashboard (position, tier, link)."""
    signup = await referral_service.resolve_signup_by_token(
        db, code, _bearer_token(credentials)
    )
    if signup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    payload = await referral_service.referral_status_payload(db, signup)
    return ReferralStatus(name=signup.name, **payload)


@router.post("/exchange", response_model=ReferralVerifyResponse)
@limiter.limit("30/minute")
async def verify_referral(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: ReferralExchangeRequest,
) -> ReferralVerifyResponse:
    """Confirm an email, credit the referrer, and hand back a dashboard key.

    ``v`` is the single-use token from the confirmation email and is consumed
    here; the returned ``access_token`` is what the page keeps for subsequent
    ``/status`` reads. A replayed link 404s — by then the browser already holds
    the access token from the first click.
    """
    verified = await referral_service.verify_signup(db, body.code, body.token)
    if verified is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    signup, access_token, _credited_referrer_id = verified

    payload = await referral_service.referral_status_payload(db, signup)
    return ReferralVerifyResponse(
        name=signup.name, access_token=access_token, **payload
    )


@router.post("/recover", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/minute")
async def recover_referral_access(
    request: Request,
    body: ReferralRecoveryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    """Mail a recovery exchange without revealing whether the address exists."""
    from sqlalchemy import func, select

    from app.models.waitlist import WaitlistSignup
    from app.services.referral_credentials import issue, recovery_allowed
    from app.tasks.referrals import send_verification_email

    email = str(body.email).strip().lower()
    if not await recovery_allowed(db, email):
        return {"ok": True}
    signup = (
        await db.execute(
            select(WaitlistSignup).where(func.lower(WaitlistSignup.email) == email)
        )
    ).scalar_one_or_none()
    if signup is not None:
        token = await issue(db, signup, "exchange")
        await db.commit()
        try:
            send_verification_email.delay(str(signup.id), token)
        except Exception:
            logger.warning("Could not queue referral recovery", exc_info=True)
    return {"ok": True}


@router.delete("/me", response_model=WaitlistDeleteResponse, status_code=202)
@limiter.limit("10/minute")
async def delete_my_waitlist_data(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str, Query(max_length=16)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(owner_bearer)
    ],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> WaitlistDeleteResponse:
    """Erase this waitlist signup and its stored resume.

    Waitlist members have no account, so ``/api/account/delete`` cannot reach
    them — this is their only way out, authenticated by the same owner token
    that reads the dashboard. Removes the Storage object alongside the row so
    erasure never leaves an orphaned file in the bucket.

    The durable receipt remains usable after the signup and owner token are
    removed, so callers can verify external erasure completion.
    """
    signup = await referral_service.resolve_signup_by_token(
        db, code, _bearer_token(credentials)
    )
    if signup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    result = await waitlist_retention_service.delete_signup(db, signup, idempotency_key)
    return WaitlistDeleteResponse(**result)
