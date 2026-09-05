"""Receipt-only deletion status; no deleted account session is required."""
import hmac
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from app.database import get_db
from app.models.deletion import DeletionRequest, DeletionAction
from app.services.deletion_service import digest

router = APIRouter(prefix='/deletions', tags=['privacy'])


@router.get('/{request_id}')
async def deletion_status(request_id: uuid.UUID, db=Depends(get_db), authorization: Annotated[str | None, Header()] = None):
    token = authorization.removeprefix('Bearer ') if authorization else ''
    row = await db.get(DeletionRequest, request_id)
    if row is None or not token or not hmac.compare_digest(row.receipt_hash, digest(token)):
        raise HTTPException(404, 'Deletion request not found')
    actions = (await db.execute(select(DeletionAction.kind, DeletionAction.status).where(DeletionAction.request_id == row.id))).all()
    return {'request_id': str(row.id), 'status': row.status,
            'components': [{'kind': kind, 'status': status} for kind, status in actions]}
