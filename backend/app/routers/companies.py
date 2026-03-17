import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.companies import CompanyResponse, CompanyStarToggle
from app.services.company_service import get_companies, get_company, toggle_company_starred

router = APIRouter(prefix="/companies", tags=["companies"])


def _to_response(company) -> CompanyResponse:
    return CompanyResponse(
        id=str(company.id),
        name=company.name,
        domain=company.domain,
        size=company.size,
        industry=company.industry,
        funding_stage=company.funding_stage,
        tech_stack=company.tech_stack,
        description=company.description,
        careers_url=company.careers_url,
        starred=company.starred,
        enriched_at=company.enriched_at.isoformat() if company.enriched_at else None,
        created_at=company.created_at.isoformat(),
    )


@router.get("", response_model=list[CompanyResponse])
async def list_companies(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    starred: bool | None = None,
):
    """List all companies, optionally filtered by starred."""
    companies = await get_companies(db, user_id, starred=starred)
    return [_to_response(c) for c in companies]


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_single_company(
    company_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a single company by ID."""
    company = await get_company(db, user_id, uuid.UUID(company_id))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return _to_response(company)


@router.put("/{company_id}/star", response_model=CompanyResponse)
async def star_company(
    company_id: str,
    body: CompanyStarToggle,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Toggle a company's starred status."""
    try:
        company = await toggle_company_starred(
            db=db,
            user_id=user_id,
            company_id=uuid.UUID(company_id),
            starred=body.starred,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(company)
