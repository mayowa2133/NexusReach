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
    JobStarToggle,
    JobResponse,
    InterviewRoundsUpdate,
    OfferDetailsUpdate,
    SearchPreferenceResponse,
    SearchPreferenceToggle,
    DiscoverRequest,
    RefreshResponse,
)
from app.services.job_service import (
    search_jobs,
    search_ats_jobs,
    get_jobs,
    get_job,
    update_job_stage,
    update_interview_rounds,
    update_offer_details,
    toggle_job_starred,
    seed_default_feeds,
    discover_jobs,
)
from app.services.search_preference_service import (
    get_search_preferences,
    toggle_search_preference,
    delete_search_preference,
)
from app.tasks.jobs import refresh_user_feeds

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
        posted_at=job.posted_at if job.posted_at and job.posted_at.strip() else None,
        match_score=job.match_score,
        score_breakdown=job.score_breakdown,
        stage=job.stage,
        tags=job.tags,
        department=job.department,
        notes=job.notes,
        experience_level=job.experience_level,
        starred=job.starred,
        applied_at=job.applied_at.isoformat() if job.applied_at else None,
        interview_rounds=job.interview_rounds,
        offer_details=job.offer_details,
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
    """Search a supported job board or ingest an exact job posting URL."""
    if not body.job_url and (not body.company_slug or not body.ats_type):
        raise HTTPException(
            status_code=400,
            detail="Provide either job_url or company_slug plus ats_type.",
        )

    try:
        jobs = await search_ats_jobs(
            db=db,
            user_id=user_id,
            company_slug=body.company_slug,
            ats_type=body.ats_type,
            job_url=body.job_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_to_response(j) for j in jobs]


@router.get("")
async def list_jobs(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    stage: str | None = None,
    sort_by: str = "score",
    starred: bool | None = None,
    employment_type: str | None = None,
    experience_level: str | None = None,
    salary_min: float | None = None,
    remote: bool | None = None,
    startup: bool | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    """List saved jobs with optional filtering and pagination."""
    jobs, total = await get_jobs(
        db, user_id, stage=stage, sort_by=sort_by, starred=starred,
        employment_type=employment_type, experience_level=experience_level,
        salary_min=salary_min, remote=remote, startup=startup, search=search,
        limit=limit, offset=offset,
    )
    return {
        "items": [_to_response(j) for j in jobs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# --- Seed Defaults ---

@router.post("/seed-defaults", response_model=RefreshResponse)
async def seed_defaults_endpoint(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Seed default job searches for first-time users. Idempotent."""
    new_count = await seed_default_feeds(db, user_id)
    return RefreshResponse(new_jobs_found=new_count)


# --- Discover ---

@router.post("/discover", response_model=RefreshResponse)
@limiter.limit("3/minute")
async def discover_jobs_endpoint(
    request: Request,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: DiscoverRequest | None = None,
):
    """Run a batch of job searches across free sources.

    Accepts an optional list of custom search queries.  Falls back to
    built-in defaults covering common roles when omitted.
    """
    queries = body.queries if body else None
    mode = body.mode if body else "default"
    new_count = await discover_jobs(db, user_id, queries=queries, mode=mode)
    return RefreshResponse(new_jobs_found=new_count)


# --- Refresh ---

@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("3/minute")
async def refresh_feeds(
    request: Request,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
):
    """Manually trigger a refresh of all enabled saved searches."""
    new_count = await refresh_user_feeds(user_id)
    return RefreshResponse(new_jobs_found=new_count)


# --- Saved Searches ---
# These must be registered before /{job_id} to avoid path parameter capture.

def _pref_to_response(pref) -> SearchPreferenceResponse:
    return SearchPreferenceResponse(
        id=str(pref.id),
        query=pref.query,
        location=pref.location,
        remote_only=pref.remote_only,
        enabled=pref.enabled,
        last_refreshed_at=pref.last_refreshed_at.isoformat() if pref.last_refreshed_at else None,
        new_jobs_found=pref.new_jobs_found or 0,
        created_at=pref.created_at.isoformat(),
        updated_at=pref.updated_at.isoformat(),
    )


@router.get("/saved-searches", response_model=list[SearchPreferenceResponse])
async def list_saved_searches(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all saved search preferences."""
    prefs = await get_search_preferences(db, user_id)
    return [_pref_to_response(p) for p in prefs]


@router.put("/saved-searches/{pref_id}", response_model=SearchPreferenceResponse)
async def update_saved_search(
    pref_id: str,
    body: SearchPreferenceToggle,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Enable or disable a saved search."""
    try:
        pref = await toggle_search_preference(db, user_id, uuid.UUID(pref_id), body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _pref_to_response(pref)


@router.delete("/saved-searches/{pref_id}")
async def remove_saved_search(
    pref_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a saved search preference."""
    try:
        await delete_search_preference(db, user_id, uuid.UUID(pref_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


# --- Single Job & Mutations (path-param routes last) ---

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


@router.put("/{job_id}/star", response_model=JobResponse)
async def star_job(
    job_id: str,
    body: JobStarToggle,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Toggle a job's starred status."""
    try:
        job = await toggle_job_starred(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
            starred=body.starred,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(job)


@router.put("/{job_id}/interviews", response_model=JobResponse)
async def update_interviews(
    job_id: str,
    body: InterviewRoundsUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a job's interview rounds."""
    try:
        job = await update_interview_rounds(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
            rounds=[r.model_dump() for r in body.interview_rounds],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(job)


@router.put("/{job_id}/offer", response_model=JobResponse)
async def update_offer(
    job_id: str,
    body: OfferDetailsUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a job's offer details."""
    try:
        job = await update_offer_details(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
            offer=body.offer_details.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(job)
