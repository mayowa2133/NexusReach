"""Auto research settings API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.auto_research import (
    CompanyAutoResearchPreferenceResponse,
    CompanyAutoResearchPreferenceUpsert,
)
from app.services.auto_research_service import (
    delete_auto_research_preference,
    list_auto_research_preferences,
    upsert_auto_research_preference,
)

router = APIRouter(prefix="/settings/auto-research", tags=["auto-research"])


def _to_response(preference) -> CompanyAutoResearchPreferenceResponse:
    return CompanyAutoResearchPreferenceResponse(
        company_name=preference.company_name,
        normalized_company_name=preference.normalized_company_name,
        auto_find_people=preference.auto_find_people,
        auto_find_emails=preference.auto_find_emails,
        created_at=preference.created_at.isoformat(),
        updated_at=preference.updated_at.isoformat(),
    )


@router.get("", response_model=list[CompanyAutoResearchPreferenceResponse])
async def list_preferences(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    preferences = await list_auto_research_preferences(db, user_id)
    return [_to_response(preference) for preference in preferences]


@router.put("", response_model=CompanyAutoResearchPreferenceResponse)
async def upsert_preference(
    body: CompanyAutoResearchPreferenceUpsert,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    preference = await upsert_auto_research_preference(
        db,
        user_id,
        company_name=body.company_name,
        auto_find_people=body.auto_find_people,
        auto_find_emails=body.auto_find_emails,
    )
    return _to_response(preference)


@router.delete("")
async def delete_preference(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    company_name: str = Query(...),
):
    try:
        await delete_auto_research_preference(
            db,
            user_id,
            company_name=company_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
