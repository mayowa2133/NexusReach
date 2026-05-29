"""Account privacy controls."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.account import AccountDeleteRequest, AccountDeleteResponse
from app.services import account_service

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/export")
async def export_account_data(
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
    """Delete the user's auth identity and all app-owned data."""
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to delete the account.",
        )

    try:
        auth_identity_deleted = await account_service.delete_supabase_auth_user(user_id)
    except account_service.AccountDeletionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    deleted_tables = await account_service.delete_user_data(db, user_id)
    return AccountDeleteResponse(
        deleted=True,
        auth_identity_deleted=auth_identity_deleted,
        deleted_tables=deleted_tables,
    )
