"""Companion extension token management.

All three endpoints require full (Supabase) auth — companion tokens are not
accepted here, so a stolen companion token can never mint a successor or
inspect its own standing. See ``services/companion_tokens`` for the design.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.companion import (
    CompanionRevokeResponse,
    CompanionStatusResponse,
    CompanionTokenResponse,
)
from app.services import companion_tokens

router = APIRouter(prefix="/companion", tags=["companion"])


@router.post("/token", response_model=CompanionTokenResponse)
async def mint_companion_token(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mint a fresh companion token, revoking any previously active ones."""
    token, row = await companion_tokens.mint_token(db, user_id)
    return CompanionTokenResponse(token=token, expires_at=row.expires_at)


@router.delete("/token", response_model=CompanionRevokeResponse)
async def revoke_companion_tokens(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Disconnect the companion by revoking all active tokens."""
    revoked = await companion_tokens.revoke_tokens(db, user_id)
    return CompanionRevokeResponse(revoked=revoked)


@router.get("/status", response_model=CompanionStatusResponse)
async def companion_status(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Server-truth connection status for the Settings companion card."""
    return await companion_tokens.get_status(db, user_id)
