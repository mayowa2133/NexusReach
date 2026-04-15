import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.schemas.profile import AutofillProfileResponse, ProfileResponse, ProfileUpdate
from app.services.resume_parser import parse_resume

router = APIRouter(prefix="/profile", tags=["profile"])


async def _seed_saved_searches(
    db: AsyncSession, user_id: uuid.UUID, profile: Profile,
) -> None:
    """Create saved searches from profile target_roles x target_locations if none exist."""
    result = await db.execute(
        select(SearchPreference).where(SearchPreference.user_id == user_id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return  # User already has saved searches — don't overwrite

    roles = profile.target_roles or []
    locations = profile.target_locations or []

    if not roles:
        return

    if locations:
        for role in roles[:3]:
            for loc in locations[:2]:
                db.add(SearchPreference(
                    user_id=user_id, query=role, location=loc, remote_only=False,
                ))
    else:
        for role in roles[:5]:
            db.add(SearchPreference(
                user_id=user_id, query=role, remote_only=False,
            ))

    await db.commit()


ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("", response_model=ProfileResponse)
async def get_profile(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ProfileResponse(
        id=str(profile.id),
        full_name=profile.full_name,
        bio=profile.bio,
        goals=profile.goals,
        tone=profile.tone,
        target_industries=profile.target_industries,
        target_company_sizes=profile.target_company_sizes,
        target_roles=profile.target_roles,
        target_locations=profile.target_locations,
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        portfolio_url=profile.portfolio_url,
        resume_parsed=profile.resume_parsed,
    )


@router.get("/autofill", response_model=AutofillProfileResponse)
async def get_autofill_profile(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
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

    # Auto-seed saved searches if profile now has target roles
    if "target_roles" in update_data or "target_locations" in update_data:
        await _seed_saved_searches(db, user_id, profile)

    # Re-score jobs if scoring-relevant fields changed
    scoring_fields = {"target_roles", "target_locations", "target_industries"}
    if scoring_fields & set(update_data.keys()):
        from app.tasks.jobs import rescore_user_jobs  # noqa: PLC0415
        rescore_user_jobs.delay(str(user_id))

    return ProfileResponse(
        id=str(profile.id),
        full_name=profile.full_name,
        bio=profile.bio,
        goals=profile.goals,
        tone=profile.tone,
        target_industries=profile.target_industries,
        target_company_sizes=profile.target_company_sizes,
        target_roles=profile.target_roles,
        target_locations=profile.target_locations,
        linkedin_url=profile.linkedin_url,
        github_url=profile.github_url,
        portfolio_url=profile.portfolio_url,
        resume_parsed=profile.resume_parsed,
    )


@router.post("/resume", response_model=ProfileResponse)
async def upload_resume(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Upload and parse a resume (PDF or DOCX)."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Upload a PDF or DOCX.",
        )

    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    file_bytes = await file.read()

    try:
        parsed = parse_resume(file_bytes, file.content_type)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse resume: {e}")

    profile.resume_parsed = parsed

    await db.commit()
    await db.refresh(profile)

    # Trigger background re-scoring of all jobs against the new resume
    from app.tasks.jobs import rescore_user_jobs  # noqa: PLC0415
    rescore_user_jobs.delay(str(user_id))

    return profile
