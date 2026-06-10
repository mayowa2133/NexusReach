"""Account privacy controls."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.schemas.account import AccountDeleteRequest, AccountDeleteResponse
from app.services import account_service

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/export")
@limiter.limit("5/minute")
async def export_account_data(
    request: Request,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Export all user-scoped NexusReach data as JSON."""
    payload = await account_service.export_user_data(db, user_id)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    filename = f"nexusreach-export-{stamp}-{user_id}.json"
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/delete", response_model=AccountDeleteResponse)
async def delete_account(
    body: AccountDeleteRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountDeleteResponse:
    """Delete all app-owned data, then the user's auth identity.

    Ordering matters (audit H3). We pre-flight that auth deletion is *possible*,
    then delete app data first (transactional — rolls back on failure), then the
    Supabase identity. This guarantees we never leave orphaned PII with the user
    locked out: the privacy-critical data removal always happens before the
    identity is touched, and the operation is idempotent on retry.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to delete the account.",
        )

    # Fail closed BEFORE destroying data if the deployment can't delete the auth
    # identity at all (e.g. missing service-role key) — otherwise we'd wipe data
    # and then be unable to complete, resurrecting an empty shell on next login.
    try:
        account_service.ensure_auth_deletion_available()
    except account_service.AccountDeletionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    deleted_tables = await account_service.delete_user_data(db, user_id)

    # Data is now gone (the privacy guarantee). A transient failure here is
    # surfaced as retryable; the user is not locked out and a retry re-runs the
    # idempotent data delete before retrying identity removal.
    try:
        auth_identity_deleted = await account_service.delete_supabase_auth_user(user_id)
    except account_service.AccountDeletionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return AccountDeleteResponse(
        deleted=True,
        auth_identity_deleted=auth_identity_deleted,
        deleted_tables=deleted_tables,
    )
