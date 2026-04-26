import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.linkedin_graph import (
    LinkedInGraphImportBatchRequest,
    LinkedInGraphImportFollowBatchRequest,
    LinkedInGraphStatusResponse,
    LinkedInGraphSyncSessionResponse,
)
from app.services import linkedin_graph_service

router = APIRouter(prefix="/linkedin-graph", tags=["linkedin-graph"])


@router.get("/status", response_model=LinkedInGraphStatusResponse)
async def get_status(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await linkedin_graph_service.get_status(db, user_id)


@router.post("/sync-session", response_model=LinkedInGraphSyncSessionResponse)
async def create_sync_session(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
async def import_file(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    try:
        return await linkedin_graph_service.import_file(
            db,
            user_id,
            filename=file.filename,
            file_bytes=await file.read(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/connections", response_model=LinkedInGraphStatusResponse)
async def clear_connections(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await linkedin_graph_service.clear_connections(db, user_id)
