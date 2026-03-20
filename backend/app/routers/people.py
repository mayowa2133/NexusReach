import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import NO_VALUE

from app.database import get_db
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.schemas.people import (
    CompanyResponse,
    PeopleSearchRequest,
    PeopleSearchResponse,
    ManualPersonRequest,
    PersonResponse,
)
from app.services.people_service import (
    search_people_at_company,
    search_people_for_job,
    enrich_person_from_linkedin,
    get_saved_people,
)
from app.services.employment_verification_service import verify_current_company_for_person

router = APIRouter(prefix="/people", tags=["people"])


def _is_mock_value(value: object) -> bool:
    return value.__class__.__module__.startswith("unittest.mock")


def _loaded_company(person) -> object | None:
    try:
        state = sa_inspect(person)
        loaded_value = state.attrs.company.loaded_value
        if loaded_value is not NO_VALUE and not _is_mock_value(loaded_value):
            return loaded_value
        explicit_company = getattr(person, "__dict__", {}).get("company")
        return explicit_company
    except Exception:
        return getattr(person, "__dict__", {}).get("company", getattr(person, "company", None))


def _serialize_company(company) -> CompanyResponse | None:
    if not company:
        return None
    payload = {field: getattr(company, field, None) for field in CompanyResponse.model_fields}
    return CompanyResponse(**payload)


def _serialize_person(person) -> PersonResponse:
    payload = {
        field: getattr(person, field, None)
        for field in PersonResponse.model_fields
        if field != "company"
    }
    payload["company"] = _serialize_company(_loaded_company(person))
    return PersonResponse(**payload)


def _serialize_people_search_result(result: dict) -> PeopleSearchResponse:
    return PeopleSearchResponse(
        company=_serialize_company(result.get("company")),
        recruiters=[_serialize_person(person) for person in result.get("recruiters", [])],
        hiring_managers=[_serialize_person(person) for person in result.get("hiring_managers", [])],
        peers=[_serialize_person(person) for person in result.get("peers", [])],
        job_context=result.get("job_context"),
    )


@router.post("/search", response_model=PeopleSearchResponse)
@limiter.limit("10/minute")
async def search_people(
    request: Request,
    body: PeopleSearchRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Search for people at a company using Apollo + GitHub.

    If job_id is provided, runs a job-aware targeted search using
    department/team context extracted from the job posting.
    """
    if body.job_id:
        try:
            job_uuid = uuid.UUID(body.job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid job_id format") from exc
        try:
            result = await search_people_for_job(
                db=db,
                user_id=user_id,
                job_id=job_uuid,
                min_relevance_score=body.min_relevance_score,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Job not found")
        return _serialize_people_search_result(result)

    result = await search_people_at_company(
        db=db,
        user_id=user_id,
        company_name=body.company_name,
        roles=body.roles,
        github_org=body.github_org,
    )
    return _serialize_people_search_result(result)


@router.post("/enrich", response_model=PersonResponse)
@limiter.limit("10/minute")
async def enrich_person(
    request: Request,
    body: ManualPersonRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Enrich a person from their LinkedIn URL (manual input)."""
    person = await enrich_person_from_linkedin(
        db=db,
        user_id=user_id,
        linkedin_url=body.linkedin_url,
    )
    return _serialize_person(person)


@router.get("", response_model=list[PersonResponse])
async def list_people(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    company_id: str | None = None,
):
    """List all saved people for the current user."""
    cid = uuid.UUID(company_id) if company_id else None
    people = await get_saved_people(db, user_id, cid)
    return [_serialize_person(person) for person in people]


@router.post("/verify-current-company/{person_id}", response_model=PersonResponse)
@limiter.limit("10/minute")
async def verify_current_company(
    request: Request,
    person_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Manually verify a saved person's current employer."""
    try:
        person_uuid = uuid.UUID(person_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid person_id format") from exc

    try:
        person = await verify_current_company_for_person(
            db=db,
            user_id=user_id,
            person_id=person_uuid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_person(person)
