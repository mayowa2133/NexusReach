import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.person import Person
from app.services.known_people_service import expire_known_person
from app.services.people.hiring_team_capture import ingest_hiring_team_capture

from app.database import get_db
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.observability import capture_event
from app.utils.discovery_rate_limit import check_discovery_rate_limit
from app.schemas.people import (
    LinkedInPageCaptureRequest,
    PeopleSearchRequest,
    PeopleSearchResponse,
    ManualPersonRequest,
    PersonResponse,
    SearchLogResponse,
)
from app.services.people import (
    search_people_at_company,
    search_people_for_job,
    enrich_person_from_linkedin,
    get_saved_people,
    get_search_history,
    persist_linkedin_page_capture,
)
from app.services.people.serialize import (
    _serialize_people_search_result,
    _serialize_person,
    snapshot_to_search_response,
)
from app.services.employment_verification_service import verify_current_company_for_person
from app.services.job_research_snapshot_service import (
    evict_person_from_job_research_snapshots,
    get_job_research_snapshot,
    save_job_research_snapshot,
    snapshot_serve_decision,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/people", tags=["people"])


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

        # Stale-while-revalidate: serve a saved snapshot instantly when one is
        # usable, refreshing in the background if it's aging. force_refresh skips
        # the cache and runs live.
        if not body.force_refresh:
            try:
                snapshot = await get_job_research_snapshot(db, user_id=user_id, job_id=job_uuid)
            except Exception:
                # Snapshot lookup is best-effort — never block Find People on it;
                # fall through to a live search.
                logger.debug("Snapshot lookup failed; running live search", exc_info=True)
                snapshot = None
            decision = snapshot_serve_decision(
                snapshot,
                requested_target_count_per_bucket=body.target_count_per_bucket,
            )
            if decision != "miss":
                if decision == "stale":
                    try:
                        from app.tasks.auto_prospect import refresh_job_research_snapshot
                        refresh_job_research_snapshot.delay(
                            str(user_id), str(job_uuid), body.target_count_per_bucket,
                        )
                    except Exception:
                        logger.debug("Failed to queue snapshot refresh", exc_info=True)
                response = snapshot_to_search_response(snapshot)
                capture_event(str(user_id), "people_searched", properties={
                    "recruiters_found": len(response.recruiters),
                    "hiring_managers_found": len(response.hiring_managers),
                    "peers_found": len(response.peers),
                    "your_connections_found": len(response.your_connections),
                    "has_job_context": True,
                    "served_from_snapshot": True,
                    "snapshot_freshness": decision,
                })
                return response

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
        capture_event(str(user_id), "people_searched", properties={
            "recruiters_found": len(response.recruiters),
            "hiring_managers_found": len(response.hiring_managers),
            "peers_found": len(response.peers),
            "your_connections_found": len(response.your_connections),
            "has_job_context": True,
            "served_from_snapshot": False,
        })
        return response

    result = await search_people_at_company(
        db=db,
        user_id=user_id,
        company_name=body.company_name,
        roles=body.roles,
        github_org=body.github_org,
        target_count_per_bucket=body.target_count_per_bucket,
    )
    response = _serialize_people_search_result(result)
    capture_event(str(user_id), "people_searched", properties={
        "recruiters_found": len(response.recruiters),
        "hiring_managers_found": len(response.hiring_managers),
        "peers_found": len(response.peers),
        "your_connections_found": len(response.your_connections),
        "has_job_context": False,
    })
    return response


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
    capture_event(str(user_id), "contact_enriched", properties={"has_email": bool(getattr(person, "work_email", None))})
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


class PersonFeedbackRequest(BaseModel):
    feedback: Literal["wrong_person", "not_at_company", "helpful"]


@router.post("/{person_id}/feedback")
async def submit_person_feedback(
    person_id: uuid.UUID,
    body: PersonFeedbackRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Record contact-quality feedback and evict bad cache rows immediately."""
    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    profile_data = dict(person.profile_data or {})
    profile_data["user_feedback"] = body.feedback
    person.profile_data = profile_data

    evicted = False
    snapshots_updated = 0
    if body.feedback in ("wrong_person", "not_at_company"):
        if body.feedback == "not_at_company":
            person.current_company_verified = False
        company_name = person.company.name if person.company else None
        if company_name:
            try:
                evicted = await expire_known_person(
                    db, company_name=company_name, full_name=person.full_name
                )
            except Exception:
                logger.warning("known-people eviction failed", exc_info=True)
        try:
            snapshots_updated = await evict_person_from_job_research_snapshots(
                db, user_id=user_id, person_id=person.id
            )
        except Exception:
            logger.warning("job snapshot contact eviction failed", exc_info=True)
    await db.commit()
    capture_event(
        str(user_id),
        "contact_feedback",
        properties={
            "feedback": body.feedback,
            "cache_evicted": evicted,
            "snapshots_updated": snapshots_updated,
        },
    )
    return {
        "ok": True,
        "cache_evicted": evicted,
        "snapshots_updated": snapshots_updated,
    }


class HiringTeamMember(BaseModel):
    name: str
    headline: str | None = None
    role_label: str | None = None
    profile_url: str | None = None


class HiringTeamCaptureRequest(BaseModel):
    company_name: str
    members: list[HiringTeamMember]
    job_id: str | None = None
    job_title: str | None = None


@router.post("/hiring-team-capture")
async def hiring_team_capture(
    body: HiringTeamCaptureRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Ingest the LinkedIn 'Meet the hiring team' panel from the companion.

    Stores the captured contacts as verified people in the right bucket and
    caches them for the company. These are the literal req owners LinkedIn
    attached to the posting.
    """
    job_uuid: uuid.UUID | None = None
    if body.job_id:
        try:
            job_uuid = uuid.UUID(body.job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid job_id format") from exc

    result = await ingest_hiring_team_capture(
        db,
        user_id,
        company_name=body.company_name,
        members=[m.model_dump() for m in body.members],
        job_id=job_uuid,
        job_title=body.job_title,
    )
    capture_event(
        str(user_id),
        "hiring_team_captured",
        properties={
            "stored": result["stored"],
            "recruiters": result["recruiters"],
            "hiring_managers": result["hiring_managers"],
        },
    )
    return {
        "stored": result["stored"],
        "recruiters": result["recruiters"],
        "hiring_managers": result["hiring_managers"],
    }
