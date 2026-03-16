import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.schemas.jobs import (
    JobSearchRequest,
    ATSSearchRequest,
    JobStageUpdate,
    JobResponse,
)
from app.services.job_service import (
    search_jobs,
    search_ats_jobs,
    get_jobs,
    get_job,
    update_job_stage,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_response(job) -> JobResponse:
    return JobResponse(
        id=str(job.id),
        title=job.title,
        company_name=job.company_name,
        company_logo=job.company_logo,
        location=job.location,
        remote=job.remote,
        url=job.url,
        description=job.description,
        employment_type=job.employment_type,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        source=job.source,
        ats=job.ats,
        posted_at=job.posted_at,
        match_score=job.match_score,
        score_breakdown=job.score_breakdown,
        stage=job.stage,
        tags=job.tags,
        department=job.department,
        notes=job.notes,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


@router.post("/search", response_model=list[JobResponse])
@limiter.limit("10/minute")
async def search(
    request: Request,
    body: JobSearchRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Search for jobs across multiple sources."""
    jobs = await search_jobs(
        db=db,
        user_id=user_id,
        query=body.query,
        location=body.location,
        remote_only=body.remote_only,
        sources=body.sources,
    )
    return [_to_response(j) for j in jobs]


@router.post("/search/ats", response_model=list[JobResponse])
async def search_ats(
    body: ATSSearchRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Search a specific ATS board (Greenhouse, Lever, Ashby)."""
    jobs = await search_ats_jobs(
        db=db,
        user_id=user_id,
        company_slug=body.company_slug,
        ats_type=body.ats_type,
    )
    return [_to_response(j) for j in jobs]


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    stage: str | None = None,
    sort_by: str = "score",
):
    """List all saved jobs, optionally filtered by kanban stage."""
    jobs = await get_jobs(db, user_id, stage=stage, sort_by=sort_by)
    return [_to_response(j) for j in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_single_job(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a single job by ID."""
    job = await get_job(db, user_id, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)


@router.put("/{job_id}/stage", response_model=JobResponse)
async def update_stage(
    job_id: str,
    body: JobStageUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a job's kanban stage."""
    try:
        job = await update_job_stage(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
            stage=body.stage,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(job)
