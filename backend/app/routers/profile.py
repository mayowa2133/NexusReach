import base64
import binascii
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_companion_or_user_id, get_current_user_id
from app.middleware.rate_limit import limiter
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.schemas.profile import (
    AutofillProfileResponse,
    LinkedInProfileImportRequest,
    LinkedInProfileImportResponse,
    ProfileResponse,
    ProfileUpdate,
    ResumeUploadJsonRequest,
)
from app.services.profile_linkedin_import import merge_linkedin_profile
from app.utils.sandboxed_process import run_in_sandbox_async
from app.utils.uploads import read_upload_capped

router = APIRouter(prefix="/profile", tags=["profile"])


def _serialize_profile(profile: Profile) -> ProfileResponse:
    return ProfileResponse(
        id=str(profile.id),
        full_name=profile.full_name,
        bio=profile.bio,
        goals=profile.goals,
        tone=profile.tone,
        target_industries=profile.target_industries,
        target_company_sizes=profile.target_company_sizes,
        target_roles=profile.target_roles,
        target_occupations=profile.target_occupations,
        target_locations=profile.target_locations,
        job_preferences=(
            profile.job_preferences
            if isinstance(profile.job_preferences, dict)
            else {}
        ),
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        portfolio_url=profile.portfolio_url,
        resume_parsed=profile.resume_parsed,
        resume_auto_accept_inferred=profile.resume_auto_accept_inferred,
    )


def _seed_queries_from_profile(profile: Profile) -> list[str]:
    """Derive saved-search query strings from a profile.

    Prefers explicit free-text ``target_roles``; otherwise falls back to the
    occupation taxonomy's representative query per ``target_occupations``. The
    fallback is essential: the product is occupation-aware, so a user who
    onboards by picking occupations (and no free-text roles) must still get
    seeded — without it their feed never enters the background-refresh pipeline
    (which is gated on having an enabled saved search) and silently freezes.
    """
    roles = [r for r in (profile.target_roles or []) if r and r.strip()]
    if roles:
        return roles[:3]

    from app.services.occupation_taxonomy import occupations_for_keys  # noqa: PLC0415

    queries: list[str] = []
    for occ in occupations_for_keys(profile.target_occupations or [])[:3]:
        query = occ.default_search_queries[0] if occ.default_search_queries else occ.label
        if query:
            queries.append(query)
    return queries


async def _seed_saved_searches(
    db: AsyncSession, user_id: uuid.UUID, profile: Profile,
) -> bool:
    """Create saved searches from the profile if the user has none yet.

    Idempotent: skips entirely when any saved search already exists, so it never
    overwrites user-curated searches. Seeds from target_roles when present, else
    from target_occupations (see ``_seed_queries_from_profile``). Returns True
    when it actually seeded new searches (the caller uses this to fire a one-time
    cold-start discovery so the feed fills immediately instead of waiting for the
    next background beat).
    """
    result = await db.execute(
        select(SearchPreference).where(SearchPreference.user_id == user_id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return False  # User already has saved searches — don't overwrite

    queries = _seed_queries_from_profile(profile)
    if not queries:
        return False

    locations = profile.target_locations or []
    if locations:
        for query in queries[:3]:
            for loc in locations[:2]:
                db.add(SearchPreference(
                    user_id=user_id, query=query, location=loc, remote_only=False,
                ))
    else:
        for query in queries[:5]:
            db.add(SearchPreference(
                user_id=user_id, query=query, remote_only=False,
            ))

    await db.commit()
    return True


ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _normalize_resume_content_type(content_type: str | None, filename: str | None) -> str:
    normalized = (content_type or "").strip().lower()
    if normalized in ALLOWED_CONTENT_TYPES:
        return normalized

    lowered_name = (filename or "").lower()
    for extension, inferred_type in ALLOWED_EXTENSIONS.items():
        if lowered_name.endswith(extension):
            return inferred_type

    allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type: {content_type}. Upload a {allowed} resume.",
    )


async def _get_profile_or_404(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


async def _parse_and_store_resume(
    *,
    db: AsyncSession,
    profile: Profile,
    file_bytes: bytes,
    content_type: str,
) -> Profile:
    # Parsing runs in a fresh, killable process with no network and OS resource
    # limits. A parser hang/OOM cannot consume the API worker.
    try:
        result = await run_in_sandbox_async(
            "app.services.resume_parser",
            "parse_resume_document",
            file_bytes,
            content_type,
            timeout_seconds=settings.parser_sandbox_timeout_seconds,
            memory_bytes=settings.parser_sandbox_memory_bytes,
            cpu_seconds=settings.parser_sandbox_cpu_seconds,
            output_bytes=settings.parser_sandbox_output_bytes,
        )
        raw_text = result["raw_text"]
        parsed = result["parsed"]
    except Exception as e:
        raise HTTPException(status_code=422, detail="Failed to parse resume safely.") from e

    profile.resume_raw = raw_text
    profile.resume_parsed = parsed

    contact = parsed.get("contact") or {}
    contact_urls = contact.get("urls") or []
    if not profile.full_name and contact.get("name"):
        profile.full_name = contact["name"]
    if not profile.linkedin_url:
        for url in contact_urls:
            if "linkedin.com/in/" in url.lower():
                profile.linkedin_url = url
                break
    if not profile.github_url:
        for url in contact_urls:
            lowered = url.lower()
            if "github.com/" in lowered and "/in/" not in lowered:
                profile.github_url = url
                break

    await db.commit()
    await db.refresh(profile)

    # Trigger background re-scoring of all jobs against the new resume
    from app.tasks.jobs import rescore_user_jobs  # noqa: PLC0415
    rescore_user_jobs.delay(str(profile.user_id))

    return profile


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _serialize_profile(profile)


@router.get("/autofill", response_model=AutofillProfileResponse)
async def get_autofill_profile(
    # Companion auth: this is the extension's profile fetch.
    user_id: Annotated[uuid.UUID, Depends(get_companion_or_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Lightweight profile endpoint optimized for Chrome extension autofill."""
    from app.models.user import User  # noqa: PLC0415

    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Get user email
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    email = user.email if user else None

    parsed = profile.resume_parsed or {}
    skills = parsed.get("skills", [])
    experience = parsed.get("experience", [])
    education_list = parsed.get("education", [])

    # Derive first/last name from full_name
    first_name = None
    last_name = None
    if profile.full_name:
        parts = profile.full_name.strip().split(None, 1)
        first_name = parts[0] if parts else None
        last_name = parts[1] if len(parts) > 1 else None

    # Current company/title from most recent experience
    current_company = None
    current_title = None
    if experience:
        latest = experience[0]
        current_company = latest.get("company")
        current_title = latest.get("title")

    # Years of experience estimate
    years_exp = str(len(experience)) if experience else None

    # Location from target_locations
    location = profile.target_locations[0] if profile.target_locations else None

    # Education summary
    edu_summary = None
    if education_list:
        e = education_list[0]
        degree = e.get("degree", "")
        field = e.get("field", "")
        inst = e.get("institution", "")
        edu_summary = f"{degree} {field}, {inst}".strip(", ")

    return AutofillProfileResponse(
        full_name=profile.full_name,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=None,  # Not stored in profile v1
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        portfolio_url=profile.portfolio_url,
        location=location,
        current_company=current_company,
        current_title=current_title,
        years_experience=years_exp,
        education=edu_summary,
        skills=skills[:20],
        target_roles=profile.target_roles or [],
    )


@router.put("", response_model=ProfileResponse)
async def update_profile(
    data: ProfileUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)

    # Auto-seed saved searches when the user sets what/where they're targeting.
    # target_occupations is included because it is now the primary targeting field
    # (occupation-aware discovery); without it an occupation-only profile would
    # never seed a saved search and its feed would never auto-refresh.
    seed_trigger_fields = {"target_roles", "target_locations", "target_occupations"}
    if seed_trigger_fields & set(update_data.keys()):
        seeded = await _seed_saved_searches(db, user_id, profile)
        # First time we enroll this user into background ingestion — fill the feed
        # right away so jobs appear on their next Jobs visit without a button.
        if seeded and not settings.demo_mode:
            from app.tasks.jobs import discover_for_user  # noqa: PLC0415
            discover_for_user.delay(str(user_id))

    # Re-score jobs if scoring-relevant fields changed
    scoring_fields = {
        "target_roles", "target_locations", "target_industries", "target_occupations",
        "job_preferences",
    }
    if scoring_fields & set(update_data.keys()) and not settings.demo_mode:
        from app.tasks.jobs import rescore_user_jobs  # noqa: PLC0415
        rescore_user_jobs.delay(str(user_id))

    return _serialize_profile(profile)


@router.post("/import-linkedin", response_model=LinkedInProfileImportResponse)
@limiter.limit("10/minute")
async def import_linkedin_profile(
    request: Request,
    body: LinkedInProfileImportRequest,
    # Companion auth: the extension captures the user's own LinkedIn profile.
    user_id: Annotated[uuid.UUID, Depends(get_companion_or_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Merge the user's own captured LinkedIn profile into their profile.

    Non-destructive: fills blank fields, unions skills, and appends
    positions/education into ``resume_parsed`` (feeding warm-path affinity).
    A parsed resume stays authoritative.
    """
    profile = await _get_profile_or_404(db, user_id)
    changed = merge_linkedin_profile(profile, body.model_dump())
    await db.commit()
    await db.refresh(profile)
    return LinkedInProfileImportResponse(profile=_serialize_profile(profile), **changed)


@router.post("/resume", response_model=ProfileResponse)
@limiter.limit("5/minute")
async def upload_resume(
    request: Request,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Upload and parse a resume (PDF or DOCX)."""
    content_type = _normalize_resume_content_type(file.content_type, file.filename)
    profile = await _get_profile_or_404(db, user_id)

    file_bytes = await read_upload_capped(file, settings.max_resume_upload_bytes)
    profile = await _parse_and_store_resume(
        db=db,
        profile=profile,
        file_bytes=file_bytes,
        content_type=content_type,
    )
    return _serialize_profile(profile)


@router.post("/resume-json", response_model=ProfileResponse)
@limiter.limit("5/minute")
async def upload_resume_json(
    request: Request,
    payload: ResumeUploadJsonRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Upload and parse a resume through JSON/base64.

    This avoids multipart transport issues in some production browser paths.
    """
    content_type = _normalize_resume_content_type(payload.content_type, payload.filename)
    profile = await _get_profile_or_404(db, user_id)

    try:
        file_bytes = base64.b64decode(payload.file_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 resume payload.")

    if len(file_bytes) > settings.max_resume_upload_bytes:
        limit_mb = max(1, settings.max_resume_upload_bytes // (1024 * 1024))
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds the maximum size of {limit_mb} MB.",
        )

    profile = await _parse_and_store_resume(
        db=db,
        profile=profile,
        file_bytes=file_bytes,
        content_type=content_type,
    )
    return _serialize_profile(profile)
