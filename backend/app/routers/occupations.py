"""Public read-only endpoint exposing the occupation taxonomy to the frontend."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.occupation_taxonomy import OCCUPATIONS

router = APIRouter(prefix="/occupations", tags=["occupations"])


class OccupationResponse(BaseModel):
    key: str
    label: str
    department_bucket: str
    engineering_flavored: bool
    startup_friendly: bool


@router.get("", response_model=list[OccupationResponse])
async def list_occupations() -> list[OccupationResponse]:
    """Return every supported occupation in stable display order."""
    return [
        OccupationResponse(
            key=occ.key,
            label=occ.label,
            department_bucket=occ.department_bucket,
            engineering_flavored=occ.engineering_flavored,
            startup_friendly=occ.startup_friendly,
        )
        for occ in OCCUPATIONS
    ]
