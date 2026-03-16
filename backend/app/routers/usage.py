"""API usage tracking routes — view daily consumption."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.api_usage import DailyUsageResponse
from app.services import api_usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/daily", response_model=DailyUsageResponse)
async def get_daily_usage(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get today's API usage summary for the current user."""
    return await api_usage_service.get_daily_usage(db, user_id)
