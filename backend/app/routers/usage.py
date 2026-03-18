"""API usage tracking routes — view daily consumption."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.api_usage import DailyUsageResponse, UsageRecordResponse
from app.services import api_usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/daily", response_model=DailyUsageResponse)
async def get_daily_usage(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: str | None = Query(None),
):
    """Get today's API usage summary for the current user."""
    return await api_usage_service.get_daily_usage(db, user_id, service)


@router.get("/records", response_model=list[UsageRecordResponse])
async def get_usage_records(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Return usage records for audit/debug views."""
    return await api_usage_service.get_usage_records(
        db,
        user_id,
        service=service,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
