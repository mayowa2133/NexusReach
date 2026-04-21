"""Triage API — batch networking ROI ranking."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.triage import TriageResponse
from app.services.triage_service import compute_triage

router = APIRouter(prefix="/triage", tags=["triage"])


@router.get("", response_model=TriageResponse)
async def get_triage(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    stages: Annotated[
        list[str] | None,
        Query(description="Filter by job stages (comma-separated). Omit for all stages."),
    ] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> TriageResponse:
    """Return all jobs ranked by networking ROI score."""
    return await compute_triage(db, user_id, stages=stages, limit=limit)
