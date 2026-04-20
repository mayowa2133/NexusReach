"""Interview-Prep Workspace API — per-job prep briefs."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.interview_prep import (
    InterviewPrepBriefResponse,
    InterviewPrepGenerateRequest,
    InterviewPrepUpdate,
)
from app.services.interview_prep_service import (
    delete_brief,
    generate_or_refresh_brief,
    get_brief,
    update_brief,
)

router = APIRouter(prefix="/jobs", tags=["interview-prep"])


@router.get(
    "/{job_id}/interview-prep",
    response_model=InterviewPrepBriefResponse,
)
async def get_interview_prep(
    job_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    brief = await get_brief(db, user_id=user_id, job_id=job_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Interview prep brief not found")
    return brief


@router.post(
    "/{job_id}/interview-prep",
    response_model=InterviewPrepBriefResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_interview_prep(
    job_id: uuid.UUID,
    payload: InterviewPrepGenerateRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    brief = await generate_or_refresh_brief(
        db, user_id=user_id, job_id=job_id, regenerate=payload.regenerate
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return brief


@router.patch(
    "/{job_id}/interview-prep",
    response_model=InterviewPrepBriefResponse,
)
async def patch_interview_prep(
    job_id: uuid.UUID,
    payload: InterviewPrepUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    story_map_dicts = (
        [m.model_dump(mode="json") for m in payload.story_map]
        if payload.story_map is not None
        else None
    )
    brief = await update_brief(
        db,
        user_id=user_id,
        job_id=job_id,
        user_notes=payload.user_notes,
        story_map=story_map_dicts,
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="Interview prep brief not found")
    return brief


@router.delete("/{job_id}/interview-prep")
async def delete_interview_prep(
    job_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ok = await delete_brief(db, user_id=user_id, job_id=job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Interview prep brief not found")
    return {"ok": True, "deleted": True}
