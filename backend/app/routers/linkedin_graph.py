import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_companion_or_user_id, get_current_user_id
from app.middleware.rate_limit import limiter
from app.utils.discovery_rate_limit import check_linkedin_sync_rate_limit
from app.schemas.linkedin_graph import (
    LinkedInGraphImportBatchRequest,
    LinkedInGraphImportFollowBatchRequest,
    LinkedInGraphStatusResponse,
    LinkedInGraphSyncSessionResponse,
)
from app.services import linkedin_graph_service
from app.utils.uploads import read_upload_capped

router = APIRouter(prefix="/linkedin-graph", tags=["linkedin-graph"])


@router.get("/status", response_model=LinkedInGraphStatusResponse)
async def get_status(
    # Companion auth: the extension polls staleness for auto-sync.
    user_id: Annotated[uuid.UUID, Depends(get_companion_or_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await linkedin_graph_service.get_status(db, user_id)


@router.post("/sync-session", response_model=LinkedInGraphSyncSessionResponse)
async def create_sync_session(
    # Companion auth: the extension starts sync sessions on its own (auto-sync).
    user_id: Annotated[uuid.UUID, Depends(get_companion_or_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _rate_check: Annotated[None, Depends(check_linkedin_sync_rate_limit)],
):
    return await linkedin_graph_service.create_sync_session(db, user_id)


@router.post("/import-batch", response_model=LinkedInGraphStatusResponse)
async def import_batch(
    body: LinkedInGraphImportBatchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await linkedin_graph_service.import_batch_with_session(
            db,
            body.session_token,
            [connection.model_dump() for connection in body.connections],
            is_final_batch=body.is_final_batch,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import-follow-batch", response_model=LinkedInGraphStatusResponse)
async def import_follow_batch(
    body: LinkedInGraphImportFollowBatchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await linkedin_graph_service.import_follow_batch_with_session(
            db,
            body.session_token,
            [follow.model_dump() for follow in body.follows],
            is_final_batch=body.is_final_batch,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import-file", response_model=LinkedInGraphStatusResponse)
@limiter.limit("5/minute")
async def import_file(
    request: Request,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    file_bytes = await read_upload_capped(file, settings.max_linkedin_upload_bytes)
    try:
        return await linkedin_graph_service.import_file(
            db,
            user_id,
            filename=file.filename,
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/connections", response_model=LinkedInGraphStatusResponse)
async def clear_connections(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await linkedin_graph_service.clear_connections(db, user_id)
