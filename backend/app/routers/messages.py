import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.messages import (
    DraftRequest,
    EditRequest,
    MessageResponse,
    DraftResponse,
)
from app.services.message_service import (
    draft_message,
    update_message,
    mark_copied,
    get_messages,
    get_message,
)

router = APIRouter(prefix="/messages", tags=["messages"])


def _to_response(msg, person=None) -> MessageResponse:
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
        person_name=person.full_name if person else None,
        person_title=person.title if person else None,
        created_at=msg.created_at.isoformat(),
        updated_at=msg.updated_at.isoformat(),
    )


@router.post("/draft", response_model=DraftResponse)
async def create_draft(
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DraftResponse(
        message=_to_response(result["message"], result["person"]),
        reasoning=result["reasoning"],
        token_usage=result["token_usage"],
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
