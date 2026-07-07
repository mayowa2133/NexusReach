"""Public pre-launch waitlist capture + token-gated admin export.

``POST /api/waitlist`` is unauthenticated (prospective users have no account)
and rate-limited by IP. ``GET /api/waitlist`` is guarded by a shared-secret
header so the owner can export entries to email at launch; it is disabled
entirely unless ``NEXUSREACH_WAITLIST_ADMIN_TOKEN`` is configured.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.schemas.waitlist import (
    WaitlistEntry,
    WaitlistExportResponse,
    WaitlistSignupCreate,
    WaitlistSignupResponse,
)
from app.services.waitlist_service import (
    list_waitlist_signups,
    upsert_waitlist_signup,
)

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.post("", response_model=WaitlistSignupResponse)
@limiter.limit("10/minute")
async def join_waitlist(
    request: Request,
    payload: WaitlistSignupCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WaitlistSignupResponse:
    """Capture a landing-page waitlist submission (idempotent per email)."""
    _entry, already = await upsert_waitlist_signup(db, payload)
    return WaitlistSignupResponse(ok=True, already_on_list=already)


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
            )
            for r in rows
        ],
    )
