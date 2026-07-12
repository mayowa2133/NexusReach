import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.observability import capture_event
from app.models.settings import UserSettings
from app.schemas.email import (
    OAuthCallbackRequest,
    OAuthUrlResponse,
    EmailFindResponse,
    EmailLookupRequest,
    EmailLookupResponse,
    EmailVerifyResponse,
    StageDraftsRequest,
    StageDraftsResponse,
    StageDraftRequest,
    StageDraftResponse,
    SendMessageRequest,
    SendMessageResponse,
    CancelSendResponse,
    EmailConnectionStatus,
)
from app.services.oauth_token_crypto import is_encrypted_refresh_token
from app.services.email_lookup_service import lookup_email
from app.services import gmail_service, outlook_service
from app.services import oauth_transaction_service
from app.services.draft_staging_service import (
    stage_message_draft,
    stage_message_drafts,
    send_staged_message,
)
from app.services.email_finder_service import find_email_for_person, verify_person_email
from app.utils.origins import allowed_frontend_origins, origin_of
from app.utils.action_budget import enforce_action_budget

router = APIRouter(prefix="/email", tags=["email"])


def _validate_redirect_uri(redirect_uri: str) -> str:
    """Reject OAuth redirect_uris that aren't one of our known frontends.

    Defense-in-depth against open-redirect / token-leak: only origins we serve
    may be used (audit pass-2 P15). The allowlist is production-aware (audit
    M6) — localhost dev origins are NOT trusted in production.
    """
    origin = origin_of(redirect_uri)
    allowed = allowed_frontend_origins()
    if not origin or (allowed and origin not in allowed):
        raise HTTPException(status_code=400, detail="redirect_uri is not allowed.")
    expected = f"{origin}/settings"
    if redirect_uri != expected:
        raise HTTPException(status_code=400, detail="redirect_uri must match the registered callback.")
    return expected


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
    capture_event(str(user_id), "email_found", properties={"found": bool(result.get("email")), "mode": mode})
    return result


@router.post("/verify/{person_id}", response_model=EmailVerifyResponse)
@limiter.limit("5/minute")
async def verify_email(
    request: Request,
    person_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Verify an existing stored email address via Hunter.io."""
    await enforce_action_budget(
        user_id,
        action="email_verify",
        limit=settings.email_verify_daily_limit,
    )
    try:
        result = await verify_person_email(db, user_id, uuid.UUID(person_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/lookup", response_model=EmailLookupResponse)
@limiter.limit("20/minute")
async def lookup_hiring_manager_email(
    request: Request,
    body: EmailLookupRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Look up a hiring manager's email from a LinkedIn URL or name + company.

    Free-only: SMTP RCPT TO verification, then ranked pattern suggestions.
    No Hunter, no Proxycurl. If verification fails, returns top 3 best guesses.
    """
    result = await lookup_email(
        db,
        linkedin_url=body.linkedin_url,
        first_name=body.first_name,
        last_name=body.last_name,
        company_name=body.company_name,
        company_domain=body.company_domain,
    )
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
        gmail_connected=(
            bool(user_settings and user_settings.gmail_connected)
            and is_encrypted_refresh_token(user_settings.gmail_refresh_token)
        ),
        outlook_connected=(
            bool(user_settings and user_settings.outlook_connected)
            and is_encrypted_refresh_token(user_settings.outlook_refresh_token)
        ),
    )


@router.get("/gmail/auth-url", response_model=OAuthUrlResponse)
@limiter.limit("5/minute")
async def gmail_auth_url(
    request: Request,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    redirect_uri: str = Query(...),
):
    """Get the Gmail OAuth consent URL."""
    safe_redirect_uri = _validate_redirect_uri(redirect_uri)
    await enforce_action_budget(
        user_id,
        action="oauth_transaction",
        limit=settings.oauth_transaction_daily_limit,
    )
    try:
        state, challenge = await oauth_transaction_service.create_transaction(
            user_id=user_id, provider="gmail", redirect_uri=safe_redirect_uri
        )
    except oauth_transaction_service.OAuthTransactionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    url = gmail_service.get_auth_url(safe_redirect_uri, state=state, code_challenge=challenge)
    return OAuthUrlResponse(auth_url=url, provider="gmail")


@router.post("/oauth/connect")
async def complete_oauth_connect(
    body: OAuthCallbackRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Consume a one-time OAuth transaction and connect its bound provider."""
    try:
        transaction = await oauth_transaction_service.consume_transaction(
            state=body.state, user_id=user_id
        )
    except oauth_transaction_service.OAuthTransactionInvalidError:
        raise HTTPException(status_code=400, detail="Invalid, expired, or already used OAuth state.")
    except oauth_transaction_service.OAuthTransactionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        if transaction.provider == "gmail":
            await gmail_service.connect_gmail(
                db, user_id, body.code, transaction.redirect_uri,
                code_verifier=transaction.code_verifier,
            )
        elif transaction.provider == "outlook":
            await outlook_service.connect_outlook(
                db, user_id, body.code, transaction.redirect_uri,
                code_verifier=transaction.code_verifier,
            )
        else:  # Defensive guard for corrupted transaction data.
            raise ValueError("Unsupported OAuth provider.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "connected", "provider": transaction.provider}


@router.post("/gmail/disconnect")
async def gmail_disconnect(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Disconnect Gmail."""
    await gmail_service.disconnect_gmail(db, user_id)
    return {"status": "disconnected", "provider": "gmail"}


@router.get("/outlook/auth-url", response_model=OAuthUrlResponse)
@limiter.limit("5/minute")
async def outlook_auth_url(
    request: Request,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    redirect_uri: str = Query(...),
):
    """Get the Outlook OAuth consent URL."""
    safe_redirect_uri = _validate_redirect_uri(redirect_uri)
    await enforce_action_budget(
        user_id,
        action="oauth_transaction",
        limit=settings.oauth_transaction_daily_limit,
    )
    try:
        state, challenge = await oauth_transaction_service.create_transaction(
            user_id=user_id, provider="outlook", redirect_uri=safe_redirect_uri
        )
    except oauth_transaction_service.OAuthTransactionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    url = outlook_service.get_auth_url(safe_redirect_uri, state=state, code_challenge=challenge)
    return OAuthUrlResponse(auth_url=url, provider="outlook")


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

    capture_event(str(user_id), "email_draft_staged", properties={"provider": body.provider})
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


# --- Sending ---


@router.post("/send", response_model=SendMessageResponse)
@limiter.limit("5/minute")
async def send_message(
    request: Request,
    body: SendMessageRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Send a staged email message via connected provider (Gmail or Outlook)."""
    try:
        result = await send_staged_message(
            db=db,
            user_id=user_id,
            message_id=uuid.UUID(body.message_id),
            provider=body.provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SendMessageResponse(
        message_id=result["message_id"],
        provider=result["provider"],
        status=result["status"],
    )


@router.post("/cancel-send/{message_id}", response_model=CancelSendResponse)
async def cancel_scheduled_send(
    message_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Cancel a scheduled auto-send for a message."""
    from app.models.message import Message  # noqa: PLC0415

    result = await db.execute(
        select(Message).where(
            Message.id == uuid.UUID(message_id),
            Message.user_id == user_id,
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")

    if not message.scheduled_send_at:
        raise HTTPException(status_code=400, detail="Message has no scheduled send.")

    message.scheduled_send_at = None
    await db.commit()

    return CancelSendResponse(
        message_id=str(message.id),
        status=message.status,
    )
