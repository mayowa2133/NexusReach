import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
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
    MatchAnalysisResponse,
    TailoredResumeResponse,
    ResumeArtifactResponse,
    ResumeArtifactDecisionsUpdate,
    ResumeArtifactLibraryEntry,
    ResumeBulletRewritePreview,
    JobCommandCenterResponse,
    JobResearchSnapshotResponse,
)
from app.services.job_service import (
    search_jobs,
    search_ats_jobs,
    get_jobs,
    get_job,
    get_job_command_center,
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
from app.services.resume_tailor import extract_jd_must_surface
from app.services.resume_artifact_service import (
    generate_resume_artifact_for_job,
    get_resume_artifact_for_job,
    list_resume_artifacts_for_user,
    render_resume_artifact_pdf,
    render_resume_artifact_redline_pdf,
)
from app.models.profile import Profile
from app.models.resume_artifact import ResumeArtifact
from app.models.tailored_resume import TailoredResume


import re as _re


def _compute_body_ats_score(tex: str, job_description: str) -> float | None:
    if not tex or not job_description:
        return None
    jd = extract_jd_must_surface(job_description)
    terms = jd.get("must_surface") or []
    if not terms:
        return None
    parts = _re.split(r"\\subsection\*\{Technical Skills\}", tex, maxsplit=1)
    body = parts[0].lower()
    hits = sum(1 for t in terms if t.lower() in body)
    return round(100.0 * hits / len(terms), 1)


async def _build_artifact_response(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: str,
    artifact: ResumeArtifact,
) -> ResumeArtifactResponse:
    from app.models.job import Job as _Job
    decisions = dict(artifact.rewrite_decisions or {})
    rewrites: list[dict] = []
    if artifact.tailored_resume_id:
        tr_result = await db.execute(
            select(TailoredResume).where(TailoredResume.id == artifact.tailored_resume_id)
        )
        tailored = tr_result.scalar_one_or_none()
        if tailored:
            rewrites = list(tailored.bullet_rewrites or [])

    previews: list[ResumeBulletRewritePreview] = []
    for rewrite in rewrites:
        rewrite_id = rewrite.get("id") or ""
        if not rewrite_id:
            continue
        previews.append(ResumeBulletRewritePreview(
            id=rewrite_id,
            section=rewrite.get("section") or "experience",
            experience_index=rewrite.get("experience_index"),
            project_index=rewrite.get("project_index"),
            original=rewrite.get("original") or "",
            rewritten=rewrite.get("rewritten") or "",
            reason=rewrite.get("reason") or "",
            change_type=rewrite.get("change_type") or "reframe",
            inferred_additions=list(rewrite.get("inferred_additions") or []),
            requires_user_confirm=bool(rewrite.get("requires_user_confirm")),
            decision=decisions.get(rewrite_id, "pending"),
        ))

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    auto_accept = bool(profile.resume_auto_accept_inferred) if profile else False

    job_result = await db.execute(
        select(_Job).where(_Job.id == artifact.job_id, _Job.user_id == user_id)
    )
    job = job_result.scalar_one_or_none()
    body_ats_score = _compute_body_ats_score(
        artifact.content or "", job.description or "" if job else ""
    )

    return ResumeArtifactResponse(
        id=str(artifact.id),
        job_id=job_id,
        tailored_resume_id=str(artifact.tailored_resume_id) if artifact.tailored_resume_id else None,
        format=artifact.format,
        filename=artifact.filename,
        content=artifact.content,
        generated_at=artifact.generated_at.isoformat(),
        created_at=artifact.created_at.isoformat(),
        updated_at=artifact.updated_at.isoformat(),
        rewrite_decisions=decisions,
        rewrite_previews=previews,
        auto_accept_inferred=auto_accept,
        body_ats_score=body_ats_score,
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
        mode=pref.mode or "default",
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


@router.get("/resume-library", response_model=list[ResumeArtifactLibraryEntry])
async def list_resume_library(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all saved resume artifacts for the user, newest first."""
    rows = await list_resume_artifacts_for_user(db=db, user_id=user_id)

    tailored_ids = {
        artifact.tailored_resume_id for artifact, _ in rows if artifact.tailored_resume_id
    }
    tailored_by_id: dict = {}
    if tailored_ids:
        tr_result = await db.execute(
            select(TailoredResume).where(TailoredResume.id.in_(tailored_ids))
        )
        tailored_by_id = {tr.id: tr for tr in tr_result.scalars().all()}

    entries: list[ResumeArtifactLibraryEntry] = []
    for artifact, job in rows:
        decisions = artifact.rewrite_decisions or {}
        pending = 0
        tailored = tailored_by_id.get(artifact.tailored_resume_id) if artifact.tailored_resume_id else None
        if tailored:
            for rw in tailored.bullet_rewrites or []:
                if (rw.get("change_type") or "") != "inferred_claim":
                    continue
                if decisions.get(rw.get("id")) in (None, "pending"):
                    pending += 1
        entries.append(ResumeArtifactLibraryEntry(
            id=str(artifact.id),
            job_id=str(artifact.job_id),
            job_title=job.title,
            company_name=job.company_name,
            filename=artifact.filename,
            generated_at=artifact.generated_at.isoformat(),
            updated_at=artifact.updated_at.isoformat(),
            pending_inferred_count=pending,
        ))
    return entries


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


@router.get("/{job_id}/command-center", response_model=JobCommandCenterResponse)
async def get_single_job_command_center(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return a compact command-center summary for a single saved job."""
    summary = await get_job_command_center(db, user_id, uuid.UUID(job_id))
    if not summary:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobCommandCenterResponse.model_validate(summary)


@router.get("/{job_id}/research-snapshot", response_model=JobResearchSnapshotResponse | None)
async def get_research_snapshot(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the latest persisted people-search snapshot for a job, if any."""
    from app.services.job_research_snapshot_service import (  # noqa: PLC0415
        get_job_research_snapshot,
        serialize_snapshot,
    )

    snapshot = await get_job_research_snapshot(db, user_id=user_id, job_id=uuid.UUID(job_id))
    payload = serialize_snapshot(snapshot)
    if not payload:
        return None
    return JobResearchSnapshotResponse.model_validate(payload)


@router.delete("/{job_id}/research-snapshot")
async def clear_research_snapshot(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Discard the persisted people-search snapshot for a job."""
    from app.services.job_research_snapshot_service import (  # noqa: PLC0415
        delete_job_research_snapshot,
    )

    deleted = await delete_job_research_snapshot(
        db, user_id=user_id, job_id=uuid.UUID(job_id)
    )
    return {"ok": True, "deleted": deleted}


@router.post("/{job_id}/analyze-match", response_model=MatchAnalysisResponse)
@limiter.limit("5/minute")
async def analyze_match(
    request: Request,
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get AI-powered match analysis for a job against the user's resume."""
    from sqlalchemy import select  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415
    from app.services.match_scoring import score_job, deep_analyze_match  # noqa: PLC0415

    job = await get_job(db, user_id, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile or not profile.resume_parsed:
        raise HTTPException(
            status_code=400,
            detail="Upload a resume in your profile first to analyze match.",
        )

    job_data = {
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "description": job.description,
        "remote": job.remote,
        "experience_level": job.experience_level,
    }
    score, breakdown = score_job(job_data, profile)

    try:
        analysis = await deep_analyze_match(job_data, profile, score, breakdown)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MatchAnalysisResponse(
        summary=analysis.get("summary", ""),
        strengths=analysis.get("strengths", []),
        gaps=analysis.get("gaps", []),
        recommendations=analysis.get("recommendations", []),
        match_score=score,
        model=analysis.get("model"),
    )


@router.post("/{job_id}/tailor-resume", response_model=TailoredResumeResponse)
@limiter.limit("5/minute")
async def tailor_resume_endpoint(
    request: Request,
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate AI-powered resume tailoring suggestions for a specific job."""
    from sqlalchemy import select  # noqa: PLC0415
    from app.models.profile import Profile  # noqa: PLC0415
    from app.models.tailored_resume import TailoredResume  # noqa: PLC0415
    from app.services.match_scoring import score_job  # noqa: PLC0415
    from app.services.resume_tailor import tailor_resume  # noqa: PLC0415

    job = await get_job(db, user_id, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile or not profile.resume_parsed:
        raise HTTPException(
            status_code=400,
            detail="Upload a resume in your profile first to tailor.",
        )

    job_data = {
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "description": job.description,
        "remote": job.remote,
        "experience_level": job.experience_level,
    }
    score, breakdown = score_job(job_data, profile)

    try:
        suggestions = await tailor_resume(job_data, profile, score, breakdown)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Persist the tailored resume
    tailored = TailoredResume(
        user_id=user_id,
        job_id=uuid.UUID(job_id),
        summary=suggestions.get("summary"),
        skills_to_emphasize=suggestions.get("skills_to_emphasize"),
        skills_to_add=suggestions.get("skills_to_add"),
        keywords_to_add=suggestions.get("keywords_to_add"),
        bullet_rewrites=suggestions.get("bullet_rewrites"),
        section_suggestions=suggestions.get("section_suggestions"),
        overall_strategy=suggestions.get("overall_strategy"),
        model=suggestions.get("model"),
        provider=suggestions.get("provider"),
    )
    db.add(tailored)
    await db.commit()
    await db.refresh(tailored)

    return TailoredResumeResponse(
        id=str(tailored.id),
        job_id=job_id,
        summary=suggestions.get("summary", ""),
        skills_to_emphasize=suggestions.get("skills_to_emphasize", []),
        skills_to_add=suggestions.get("skills_to_add", []),
        keywords_to_add=suggestions.get("keywords_to_add", []),
        bullet_rewrites=suggestions.get("bullet_rewrites", []),
        section_suggestions=suggestions.get("section_suggestions", []),
        overall_strategy=suggestions.get("overall_strategy", ""),
        model=suggestions.get("model"),
        created_at=tailored.created_at.isoformat(),
    )


@router.get("/{job_id}/tailor-resume", response_model=TailoredResumeResponse | None)
async def get_tailored_resume(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the most recent tailored resume for a job, if any."""
    from sqlalchemy import select  # noqa: PLC0415
    from app.models.tailored_resume import TailoredResume  # noqa: PLC0415

    result = await db.execute(
        select(TailoredResume)
        .where(
            TailoredResume.user_id == user_id,
            TailoredResume.job_id == uuid.UUID(job_id),
        )
        .order_by(TailoredResume.created_at.desc())
        .limit(1)
    )
    tailored = result.scalar_one_or_none()
    if not tailored:
        return None

    return TailoredResumeResponse(
        id=str(tailored.id),
        job_id=job_id,
        summary=tailored.summary or "",
        skills_to_emphasize=tailored.skills_to_emphasize or [],
        skills_to_add=tailored.skills_to_add or [],
        keywords_to_add=tailored.keywords_to_add or [],
        bullet_rewrites=tailored.bullet_rewrites or [],
        section_suggestions=tailored.section_suggestions or [],
        overall_strategy=tailored.overall_strategy or "",
        model=tailored.model,
        created_at=tailored.created_at.isoformat(),
    )


@router.post("/{job_id}/resume-artifact", response_model=ResumeArtifactResponse)
@limiter.limit("5/minute")
async def generate_resume_artifact(
    request: Request,
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate or refresh a submission-ready tailored resume artifact for a job."""
    try:
        artifact = await generate_resume_artifact_for_job(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await _build_artifact_response(db, user_id=user_id, job_id=job_id, artifact=artifact)


@router.get("/{job_id}/resume-artifact", response_model=ResumeArtifactResponse | None)
async def get_resume_artifact(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the latest saved resume artifact for a job, if any."""
    artifact = await get_resume_artifact_for_job(
        db=db,
        user_id=user_id,
        job_id=uuid.UUID(job_id),
    )
    if not artifact:
        return None

    return await _build_artifact_response(db, user_id=user_id, job_id=job_id, artifact=artifact)


@router.patch("/{job_id}/resume-artifact/decisions", response_model=ResumeArtifactResponse)
@limiter.limit("15/minute")
async def update_resume_artifact_decisions(
    request: Request,
    job_id: str,
    body: ResumeArtifactDecisionsUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Accept or reject proposed bullet rewrites and re-render the artifact.

    Decisions map rewrite_id -> "accepted" | "rejected" | "pending".
    Decisions for "keyword" and "reframe" rewrites are always applied; only
    "inferred_claim" rewrites require explicit acceptance (or an auto-accept
    profile flag) before they are rendered into the final PDF.
    """
    valid = {"accepted", "rejected", "pending"}
    decisions = {
        str(k): v.lower()
        for k, v in (body.decisions or {}).items()
        if isinstance(v, str) and v.lower() in valid
    }

    existing = await get_resume_artifact_for_job(
        db=db,
        user_id=user_id,
        job_id=uuid.UUID(job_id),
    )
    if existing is not None:
        merged = dict(existing.rewrite_decisions or {})
        merged.update(decisions)
    else:
        merged = decisions

    try:
        artifact = await generate_resume_artifact_for_job(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
            rewrite_decisions=merged,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await _build_artifact_response(db, user_id=user_id, job_id=job_id, artifact=artifact)


@router.get("/{job_id}/resume-artifact/pdf")
async def download_resume_artifact_pdf(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Render the saved resume artifact as a downloadable PDF."""
    artifact = await get_resume_artifact_for_job(
        db=db,
        user_id=user_id,
        job_id=uuid.UUID(job_id),
    )
    if not artifact:
        artifact = await generate_resume_artifact_for_job(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
        )

    pdf_bytes = render_resume_artifact_pdf(artifact.content)
    pdf_filename = artifact.filename.rsplit(".", 1)[0] + ".pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_filename}"',
        },
    )


@router.get("/{job_id}/resume-artifact/redline-pdf")
async def preview_resume_artifact_redline_pdf(
    job_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Render the saved resume artifact as an inline review PDF with redlines."""
    artifact = await get_resume_artifact_for_job(
        db=db,
        user_id=user_id,
        job_id=uuid.UUID(job_id),
    )
    if not artifact:
        artifact = await generate_resume_artifact_for_job(
            db=db,
            user_id=user_id,
            job_id=uuid.UUID(job_id),
        )

    response = await _build_artifact_response(
        db,
        user_id=user_id,
        job_id=job_id,
        artifact=artifact,
    )
    pdf_bytes = render_resume_artifact_redline_pdf(
        response.content,
        [preview.model_dump() for preview in response.rewrite_previews],
        response.rewrite_decisions,
        auto_accept_inferred=response.auto_accept_inferred,
    )
    pdf_filename = artifact.filename.rsplit(".", 1)[0] + "-redline.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{pdf_filename}"',
        },
    )


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
