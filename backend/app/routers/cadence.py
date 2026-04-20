"""Cadence engine API — surfaces next-action queue for Dashboard / Outreach."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.cadence import NextActionListResponse, NextActionResponse
from app.services.cadence_service import compute_next_actions, serialize_action

router = APIRouter(prefix="/cadence", tags=["cadence"])


@router.get("/next-actions", response_model=NextActionListResponse)
async def list_next_actions(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int | None = Query(default=None, ge=1, le=100),
):
    """Return ranked next-action queue for this user.

    Order: high → medium → low urgency, then oldest first within tier.
    """
    actions = await compute_next_actions(db, user_id, limit=limit)
    items = [NextActionResponse(**serialize_action(a)) for a in actions]
    return NextActionListResponse(items=items, total=len(items))
