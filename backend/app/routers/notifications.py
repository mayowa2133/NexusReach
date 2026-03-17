import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.notifications import (
    NotificationResponse,
    NotificationMarkRead,
    UnreadCountResponse,
)
from app.services.notification_service import (
    get_notifications,
    get_unread_count,
    mark_notifications_read,
    mark_all_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_response(n) -> NotificationResponse:
    return NotificationResponse(
        id=str(n.id),
        type=n.type,
        title=n.title,
        body=n.body,
        job_id=str(n.job_id) if n.job_id else None,
        company_id=str(n.company_id) if n.company_id else None,
        read=n.read,
        created_at=n.created_at.isoformat(),
    )


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """List notifications, newest first."""
    notifications = await get_notifications(
        db, user_id, unread_only=unread_only, limit=limit, offset=offset
    )
    return [_to_response(n) for n in notifications]


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get the count of unread notifications."""
    count = await get_unread_count(db, user_id)
    return UnreadCountResponse(count=count)


@router.post("/mark-read")
async def mark_read(
    body: NotificationMarkRead,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mark specific notifications as read."""
    ids = [uuid.UUID(nid) for nid in body.notification_ids]
    updated = await mark_notifications_read(db, user_id, ids)
    return {"updated": updated}


@router.post("/mark-all-read")
async def mark_all(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Mark all notifications as read."""
    updated = await mark_all_read(db, user_id)
    return {"updated": updated}
