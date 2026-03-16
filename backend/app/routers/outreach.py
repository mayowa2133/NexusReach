import uuid
from typing import Annotated
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.outreach import (
    CreateOutreachRequest,
    UpdateOutreachRequest,
    OutreachResponse,
    OutreachStats,
)
from app.services.outreach_service import (
    create_outreach_log,
    update_outreach_log,
    get_outreach_logs,
    get_outreach_log,
    get_outreach_timeline,
    get_outreach_stats,
    delete_outreach_log,
)

router = APIRouter(prefix="/outreach", tags=["outreach"])


def _to_response(log, person=None) -> OutreachResponse:
    p = person or getattr(log, "person", None)
    company = getattr(p, "company", None) if p else None
    job = getattr(log, "job", None)

    return OutreachResponse(
        id=str(log.id),
        person_id=str(log.person_id),
        job_id=str(log.job_id) if log.job_id else None,
        message_id=str(log.message_id) if log.message_id else None,
        status=log.status,
        channel=log.channel,
        notes=log.notes,
        last_contacted_at=log.last_contacted_at.isoformat() if log.last_contacted_at else None,
        next_follow_up_at=log.next_follow_up_at.isoformat() if log.next_follow_up_at else None,
        response_received=log.response_received,
        person_name=p.full_name if p else None,
        person_title=p.title if p else None,
        company_name=company.name if company else None,
        job_title=job.title if job else None,
        created_at=log.created_at.isoformat(),
        updated_at=log.updated_at.isoformat(),
    )


@router.post("", response_model=OutreachResponse)
async def create_outreach(
    body: CreateOutreachRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a new outreach log entry."""
    try:
        log = await create_outreach_log(
            db=db,
            user_id=user_id,
            person_id=uuid.UUID(body.person_id),
            status=body.status,
            channel=body.channel,
            notes=body.notes,
            job_id=uuid.UUID(body.job_id) if body.job_id else None,
            message_id=uuid.UUID(body.message_id) if body.message_id else None,
            last_contacted_at=datetime.fromisoformat(body.last_contacted_at) if body.last_contacted_at else None,
            next_follow_up_at=datetime.fromisoformat(body.next_follow_up_at) if body.next_follow_up_at else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _to_response(log)


@router.get("", response_model=list[OutreachResponse])
async def list_outreach(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = None,
    person_id: str | None = None,
    job_id: str | None = None,
):
    """List outreach logs with optional filters."""
    logs = await get_outreach_logs(
        db,
        user_id,
        status=status,
        person_id=uuid.UUID(person_id) if person_id else None,
        job_id=uuid.UUID(job_id) if job_id else None,
    )
    return [_to_response(log) for log in logs]


@router.get("/stats", response_model=OutreachStats)
async def outreach_stats(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get aggregate outreach statistics."""
    return await get_outreach_stats(db, user_id)


@router.get("/{log_id}", response_model=OutreachResponse)
async def get_single_outreach(
    log_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a single outreach log by ID."""
    log = await get_outreach_log(db, user_id, uuid.UUID(log_id))
    if not log:
        raise HTTPException(status_code=404, detail="Outreach log not found")
    return _to_response(log)


@router.get("/person/{person_id}/timeline", response_model=list[OutreachResponse])
async def person_timeline(
    person_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the outreach timeline for a specific person."""
    logs = await get_outreach_timeline(db, user_id, uuid.UUID(person_id))
    return [_to_response(log) for log in logs]


@router.put("/{log_id}", response_model=OutreachResponse)
async def update_outreach(
    log_id: str,
    body: UpdateOutreachRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update an outreach log entry."""
    updates = body.model_dump(exclude_unset=True)

    # Convert string UUIDs to UUID objects
    for field in ("job_id", "message_id"):
        if field in updates and updates[field] is not None:
            updates[field] = uuid.UUID(updates[field])

    # Convert ISO datetime strings
    for field in ("last_contacted_at", "next_follow_up_at"):
        if field in updates and updates[field] is not None:
            updates[field] = datetime.fromisoformat(updates[field])

    try:
        log = await update_outreach_log(db, user_id, uuid.UUID(log_id), **updates)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _to_response(log)


@router.delete("/{log_id}", status_code=204)
async def delete_outreach(
    log_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete an outreach log entry."""
    try:
        await delete_outreach_log(db, user_id, uuid.UUID(log_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
