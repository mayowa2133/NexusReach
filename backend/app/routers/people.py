import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import NO_VALUE

from app.database import get_db
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.utils.discovery_rate_limit import check_discovery_rate_limit
from app.schemas.people import (
    CompanyResponse,
    LinkedInPageCaptureRequest,
    PeopleSearchRequest,
    PeopleSearchResponse,
    ManualPersonRequest,
    PersonResponse,
    SearchErrorDetail,
    SearchLogResponse,
)
from app.schemas.linkedin_graph import LinkedInGraphConnectionResponse
from app.services.people_service import (
    search_people_at_company,
    search_people_for_job,
    enrich_person_from_linkedin,
    get_saved_people,
    get_search_history,
    persist_linkedin_page_capture,
)
from app.services.employment_verification_service import verify_current_company_for_person
from app.services.job_research_snapshot_service import save_job_research_snapshot

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


def _safe_value(value):
    return None if _is_mock_value(value) else value


def _serialize_linkedin_graph_connection(connection) -> LinkedInGraphConnectionResponse | None:
    if not connection:
        return None
    if isinstance(connection, dict):
        return LinkedInGraphConnectionResponse(**connection)

    payload = {
        "id": str(_safe_value(getattr(connection, "id", "")) or ""),
        "display_name": _safe_value(getattr(connection, "display_name", None)),
        "headline": _safe_value(getattr(connection, "headline", None)),
        "current_company_name": _safe_value(getattr(connection, "current_company_name", None)),
        "linkedin_url": _safe_value(getattr(connection, "linkedin_url", None)),
        "company_linkedin_url": _safe_value(getattr(connection, "company_linkedin_url", None)),
        "source": _safe_value(getattr(connection, "source", "manual_import")) or "manual_import",
        "last_synced_at": _safe_value(getattr(connection, "last_synced_at", None)),
    }
    if not payload["display_name"]:
        return None
    return LinkedInGraphConnectionResponse(**payload)


def _serialize_person(person) -> PersonResponse:
    payload = {}
    for field, field_info in PersonResponse.model_fields.items():
        if field in {"company", "warm_path_connection"}:
            continue
        value = _safe_value(getattr(person, field, None))
        if value is None and not field_info.is_required():
            continue
        payload[field] = value
    payload["company"] = _serialize_company(_loaded_company(person))
    warm_path_connection = _serialize_linkedin_graph_connection(
        getattr(person, "warm_path_connection", None)
    )
    if warm_path_connection is not None:
        payload["warm_path_connection"] = warm_path_connection
    return PersonResponse(**payload)


def _serialize_people_search_result(result: dict) -> PeopleSearchResponse:
    raw_errors = result.get("errors")
    errors = (
        [SearchErrorDetail(**e) for e in raw_errors]
        if raw_errors
        else None
    )
    return PeopleSearchResponse(
        company=_serialize_company(result.get("company")),
        your_connections=[
            LinkedInGraphConnectionResponse(**connection)
            for connection in result.get("your_connections", [])
        ],
        recruiters=[_serialize_person(person) for person in result.get("recruiters", [])],
        hiring_managers=[_serialize_person(person) for person in result.get("hiring_managers", [])],
        peers=[_serialize_person(person) for person in result.get("peers", [])],
        job_context=result.get("job_context"),
        errors=errors,
        debug=result.get("debug"),
    )


@router.post("/search", response_model=PeopleSearchResponse)
@limiter.limit("10/minute")
async def search_people(
    request: Request,
    body: PeopleSearchRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _rate_check: Annotated[None, Depends(check_discovery_rate_limit)],
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
                search_depth=body.search_depth,
                min_relevance_score=body.min_relevance_score,
                target_count_per_bucket=body.target_count_per_bucket,
                include_debug=body.include_debug,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Job not found")
        response = _serialize_people_search_result(result)
        try:
            await save_job_research_snapshot(
                db,
                user_id=user_id,
                job_id=job_uuid,
                company_name=body.company_name,
                target_count_per_bucket=body.target_count_per_bucket,
                recruiters=[r.model_dump(mode="json") for r in response.recruiters],
                hiring_managers=[m.model_dump(mode="json") for m in response.hiring_managers],
                peers=[p.model_dump(mode="json") for p in response.peers],
                your_connections=[c.model_dump(mode="json") for c in response.your_connections],
                errors=[e.model_dump(mode="json") for e in (response.errors or [])] or None,
            )
        except Exception:
            # Snapshot persistence is best-effort — never block search on it.
            pass
        return response

    result = await search_people_at_company(
        db=db,
        user_id=user_id,
        company_name=body.company_name,
        roles=body.roles,
        github_org=body.github_org,
        target_count_per_bucket=body.target_count_per_bucket,
    )
    return _serialize_people_search_result(result)


@router.post("/enrich", response_model=PersonResponse)
@limiter.limit("10/minute")
async def enrich_person(
    request: Request,
    body: ManualPersonRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _rate_check: Annotated[None, Depends(check_discovery_rate_limit)],
):
    """Enrich a person from their LinkedIn URL (manual input)."""
    person = await enrich_person_from_linkedin(
        db=db,
        user_id=user_id,
        linkedin_url=body.linkedin_url,
    )
    return _serialize_person(person)


@router.post("/{person_id}/linkedin-page-capture", response_model=PersonResponse)
@limiter.limit("20/minute")
async def save_linkedin_page_capture(
    request: Request,
    person_id: str,
    body: LinkedInPageCaptureRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _rate_check: Annotated[None, Depends(check_discovery_rate_limit)],
):
    try:
        person_uuid = uuid.UUID(person_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid person_id format") from exc

    try:
        person = await persist_linkedin_page_capture(
            db=db,
            user_id=user_id,
            person_id=person_uuid,
            payload=body.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _serialize_person(person)


@router.get("")
async def list_people(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    company_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    """List saved people with optional filtering and pagination."""
    cid = uuid.UUID(company_id) if company_id else None
    people, total = await get_saved_people(db, user_id, cid, limit=limit, offset=offset)
    return {
        "items": [_serialize_person(person) for person in people],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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


@router.get("/search/history", response_model=list[SearchLogResponse])
async def search_history(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
):
    """Return recent people discovery searches for the current user."""
    logs = await get_search_history(db, user_id, limit=min(limit, 50))
    return [
        SearchLogResponse(
            id=str(log.id),
            company_name=log.company_name,
            search_type=log.search_type,
            recruiter_count=log.recruiter_count,
            manager_count=log.manager_count,
            peer_count=log.peer_count,
            errors=log.errors,
            duration_seconds=log.duration_seconds,
            created_at=log.created_at.isoformat() if log.created_at else "",
        )
        for log in logs
    ]
