import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.schemas.profile import ProfileResponse, ProfileUpdate
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
    return profile
