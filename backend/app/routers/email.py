import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.models.settings import UserSettings
from app.schemas.email import (
    OAuthCallbackRequest,
    OAuthUrlResponse,
    EmailFindResponse,
    EmailVerifyResponse,
    StageDraftsRequest,
    StageDraftsResponse,
    StageDraftRequest,
    StageDraftResponse,
    EmailConnectionStatus,
)
from app.services import gmail_service, outlook_service
from app.services.draft_staging_service import stage_message_draft, stage_message_drafts
from app.services.email_finder_service import find_email_for_person, verify_person_email

router = APIRouter(prefix="/email", tags=["email"])


# --- Email Finding ---


@router.post("/find/{person_id}", response_model=EmailFindResponse)
@limiter.limit("10/minute")
async def find_email(
    request: Request,
    person_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    mode: str = Query("best_effort"),
):
    """Find a work email using pattern-first best-effort discovery."""
    try:
        result = await find_email_for_person(
            db,
            user_id,
            uuid.UUID(person_id),
            mode=mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.post("/verify/{person_id}", response_model=EmailVerifyResponse)
async def verify_email(
    person_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Verify an existing stored email address via Hunter.io."""
    try:
        result = await verify_person_email(db, user_id, uuid.UUID(person_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# --- OAuth Connection ---


@router.get("/status", response_model=EmailConnectionStatus)
async def connection_status(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Check which email providers are connected."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    user_settings = result.scalar_one_or_none()
    return EmailConnectionStatus(
        gmail_connected=user_settings.gmail_connected if user_settings else False,
        outlook_connected=user_settings.outlook_connected if user_settings else False,
    )


@router.get("/gmail/auth-url", response_model=OAuthUrlResponse)
async def gmail_auth_url(
    redirect_uri: str = Query(...),
):
    """Get the Gmail OAuth consent URL."""
    url = gmail_service.get_auth_url(redirect_uri)
    return OAuthUrlResponse(auth_url=url)


@router.post("/gmail/connect")
async def gmail_connect(
    body: OAuthCallbackRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Complete Gmail OAuth — exchange code for tokens."""
    try:
        await gmail_service.connect_gmail(db, user_id, body.code, body.redirect_uri)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "connected", "provider": "gmail"}


@router.post("/gmail/disconnect")
async def gmail_disconnect(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Disconnect Gmail."""
    await gmail_service.disconnect_gmail(db, user_id)
    return {"status": "disconnected", "provider": "gmail"}


@router.get("/outlook/auth-url", response_model=OAuthUrlResponse)
async def outlook_auth_url(
    redirect_uri: str = Query(...),
):
    """Get the Outlook OAuth consent URL."""
    url = outlook_service.get_auth_url(redirect_uri)
    return OAuthUrlResponse(auth_url=url)


@router.post("/outlook/connect")
async def outlook_connect(
    body: OAuthCallbackRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Complete Outlook OAuth — exchange code for tokens."""
    try:
        await outlook_service.connect_outlook(db, user_id, body.code, body.redirect_uri)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "connected", "provider": "outlook"}


@router.post("/outlook/disconnect")
async def outlook_disconnect(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Disconnect Outlook."""
    await outlook_service.disconnect_outlook(db, user_id)
    return {"status": "disconnected", "provider": "outlook"}


# --- Draft Staging ---


@router.post("/stage-draft", response_model=StageDraftResponse)
@limiter.limit("10/minute")
async def stage_draft(
    request: Request,
    body: StageDraftRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stage a message as a draft in the user's email inbox (Gmail or Outlook).

    The message must be an email-channel message with a subject and body.
    The target person must have a work_email.
    """
    try:
        draft = await stage_message_draft(
            db=db,
            user_id=user_id,
            message_id=uuid.UUID(body.message_id),
            provider=body.provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StageDraftResponse(
        draft_id=draft["draft_id"],
        provider=body.provider,
        message_id=draft.get("message_id"),
    )


@router.post("/stage-drafts", response_model=StageDraftsResponse)
@limiter.limit("5/minute")
async def stage_drafts(
    request: Request,
    body: StageDraftsRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Stage multiple email drafts sequentially with per-item results."""
    result = await stage_message_drafts(
        db=db,
        user_id=user_id,
        message_ids=[uuid.UUID(message_id) for message_id in body.message_ids],
        provider=body.provider,
    )
    return StageDraftsResponse(
        requested_count=result["requested_count"],
        staged_count=result["staged_count"],
        failed_count=result["failed_count"],
        items=result["items"],
    )
