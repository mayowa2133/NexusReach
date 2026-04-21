"""Settings API routes — Phase 9."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.settings import (
    AutoProspectResponse,
    AutoProspectUpdate,
    CadenceSettingsResponse,
    CadenceSettingsUpdate,
    GuardrailsResponse,
    GuardrailsUpdate,
    OnboardingCompleteResponse,
)
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/guardrails", response_model=GuardrailsResponse)
async def get_guardrails(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the current guardrails configuration."""
    return await settings_service.get_guardrails(db, user_id)


@router.put("/guardrails", response_model=GuardrailsResponse)
async def update_guardrails(
    body: GuardrailsUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Partially update guardrails settings."""
    payload = body.model_dump(exclude_none=True)
    return await settings_service.update_guardrails(db, user_id, payload)


@router.post("/onboarding-complete", response_model=OnboardingCompleteResponse)
async def complete_onboarding(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mark the user's onboarding as complete."""
    await settings_service.complete_onboarding(db, user_id)
    return OnboardingCompleteResponse(onboarding_completed=True)


@router.get("/auto-prospect", response_model=AutoProspectResponse)
async def get_auto_prospect(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the current auto-prospect configuration."""
    return await settings_service.get_auto_prospect(db, user_id)


@router.put("/auto-prospect", response_model=AutoProspectResponse)
async def update_auto_prospect(
    body: AutoProspectUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Partially update auto-prospect settings."""
    payload = body.model_dump(exclude_none=True)
    return await settings_service.update_auto_prospect(db, user_id, payload)


@router.get("/cadence", response_model=CadenceSettingsResponse)
async def get_cadence_settings(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the current cadence threshold configuration."""
    return await settings_service.get_cadence_settings(db, user_id)


@router.put("/cadence", response_model=CadenceSettingsResponse)
async def update_cadence_settings(
    body: CadenceSettingsUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Partially update cadence threshold settings."""
    payload = body.model_dump(exclude_none=True)
    return await settings_service.update_cadence_settings(db, user_id, payload)
