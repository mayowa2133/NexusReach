"""Known people API routes — query the global shared discovery cache."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.known_people import (
    KnownPeopleCountResponse,
    KnownPeopleSearchResponse,
    KnownPersonResponse,
)
from app.services.known_people_service import (
    get_known_people_count,
    lookup_known_people,
)

router = APIRouter(prefix="/known-people", tags=["known-people"])


@router.get("/search", response_model=KnownPeopleSearchResponse)
async def search_known_people(
    company_name: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 25,
):
    """Search the global known people cache for a company.

    Returns people previously discovered through public sources by any user.
    """
    candidates = await lookup_known_people(db, company_name=company_name, limit=limit)

    items: list[KnownPersonResponse] = []
    for c in candidates:
        pd = c.get("profile_data") or {}
        items.append(KnownPersonResponse(
            id=pd.get("known_person_id", ""),
            full_name=c.get("full_name"),
            title=c.get("title"),
            department=c.get("department"),
            seniority=c.get("seniority"),
            linkedin_url=c.get("linkedin_url"),
            github_url=c.get("github_url"),
            primary_source=c.get("source", ""),
            discovery_count=pd.get("discovery_count", 1),
            last_verified_at=None,
            verification_status=pd.get("cache_freshness", "fresh"),
            company_name=c.get("company_name"),
            company_domain=c.get("company_domain"),
        ))

    # Determine overall freshness
    statuses = {i.verification_status for i in items}
    if not items:
        freshness = "fresh"
    elif statuses == {"fresh"}:
        freshness = "fresh"
    elif "stale" in statuses and "fresh" in statuses:
        freshness = "mixed"
    elif statuses <= {"stale", "reverified"}:
        freshness = "stale"
    else:
        freshness = "mixed"

    return KnownPeopleSearchResponse(
        items=items,
        total=len(items),
        cache_freshness=freshness,
    )


@router.get("/count", response_model=KnownPeopleCountResponse)
async def known_people_count(
    company_name: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return count of known people at a company (for UI badges)."""
    count = await get_known_people_count(db, company_name=company_name)
    return KnownPeopleCountResponse(company_name=company_name, count=count)
