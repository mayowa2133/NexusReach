"""API routes for the Insights Dashboard — Phase 8."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.insights import InsightsDashboard
from app.services.insights_service import get_full_dashboard

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/dashboard", response_model=InsightsDashboard)
async def dashboard(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the full insights dashboard — all analytics in one call."""
    return await get_full_dashboard(db, user_id)
