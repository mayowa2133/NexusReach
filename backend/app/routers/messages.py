import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter
from app.schemas.messages import (
    BatchDraftItem,
    BatchDraftRequest,
    BatchDraftResponse,
    DraftRequest,
    EditRequest,
    DraftResponse,
    MessageResponse,
)
from app.schemas.people import PersonResponse
from app.services.message_service import (
    batch_draft_messages,
    draft_message,
    get_message,
    get_messages,
    mark_copied,
    update_message,
)

router = APIRouter(prefix="/messages", tags=["messages"])


def _snapshot(msg) -> dict:
    snapshot = getattr(msg, "context_snapshot", None)
    return snapshot if isinstance(snapshot, dict) else {}


def _to_response(msg, person=None) -> MessageResponse:
    snapshot = _snapshot(msg)
    return MessageResponse(
        id=str(msg.id),
        person_id=str(msg.person_id),
        channel=msg.channel,
        goal=msg.goal,
        subject=msg.subject,
        body=msg.body,
        reasoning=msg.reasoning,
        ai_model=msg.ai_model,
        status=msg.status,
        version=msg.version,
        parent_id=str(msg.parent_id) if msg.parent_id else None,
        recipient_strategy=snapshot.get("recipient_strategy"),
        primary_cta=snapshot.get("primary_cta"),
        fallback_cta=snapshot.get("fallback_cta"),
        job_id=snapshot.get("job_id"),
        person_name=person.full_name if person else None,
        person_title=person.title if person else None,
        created_at=msg.created_at.isoformat(),
        updated_at=msg.updated_at.isoformat(),
    )


def _to_batch_item(item: dict) -> BatchDraftItem:
    person = item.get("person")
    message = item.get("message")
    return BatchDraftItem(
        status=item["status"],
        person=PersonResponse.model_validate(person) if person is not None else None,
        message=_to_response(message, person) if message is not None else None,
        reason=item.get("reason"),
    )


@router.post("/draft", response_model=DraftResponse)
@limiter.limit("10/minute")
async def create_draft(
    request: Request,
    body: DraftRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Draft a new personalized message using Claude."""
    try:
        result = await draft_message(
            db=db,
            user_id=user_id,
            person_id=uuid.UUID(body.person_id),
            channel=body.channel,
            goal=body.goal,
            job_id=uuid.UUID(body.job_id) if body.job_id else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DraftResponse(
        message=_to_response(result["message"], result["person"]),
        reasoning=result["reasoning"],
        token_usage=result["token_usage"],
        recipient_strategy=result.get("recipient_strategy"),
        primary_cta=result.get("primary_cta"),
        fallback_cta=result.get("fallback_cta"),
        job_id=result.get("job_id"),
    )


@router.post("/batch-draft", response_model=BatchDraftResponse)
@limiter.limit("5/minute")
async def create_batch_drafts(
    request: Request,
    body: BatchDraftRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Draft multiple individualized email messages for a shortlist of people."""
    try:
        result = await batch_draft_messages(
            db=db,
            user_id=user_id,
            person_ids=[uuid.UUID(person_id) for person_id in body.person_ids],
            goal=body.goal,
            job_id=uuid.UUID(body.job_id) if body.job_id else None,
            include_recent_contacts=body.include_recent_contacts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return BatchDraftResponse(
        requested_count=result["requested_count"],
        ready_count=result["ready_count"],
        skipped_count=result["skipped_count"],
        failed_count=result["failed_count"],
        items=[_to_batch_item(item) for item in result["items"]],
    )


@router.put("/{message_id}", response_model=MessageResponse)
async def edit_message(
    message_id: str,
    body: EditRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Edit a message draft."""
    try:
        msg = await update_message(
            db=db,
            user_id=user_id,
            message_id=uuid.UUID(message_id),
            body=body.body,
            subject=body.subject,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _to_response(msg)


@router.post("/{message_id}/copy", response_model=MessageResponse)
async def copy_message(
    message_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mark a message as copied to clipboard."""
    try:
        msg = await mark_copied(
            db=db,
            user_id=user_id,
            message_id=uuid.UUID(message_id),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _to_response(msg)


@router.get("", response_model=list[MessageResponse])
async def list_messages(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    person_id: str | None = None,
):
    """List all messages, optionally filtered by person."""
    pid = uuid.UUID(person_id) if person_id else None
    messages = await get_messages(db, user_id, pid)
    return [_to_response(m) for m in messages]


@router.get("/{message_id}", response_model=MessageResponse)
async def get_single_message(
    message_id: str,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a single message by ID."""
    msg = await get_message(db, user_id, uuid.UUID(message_id))
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    return _to_response(msg)
