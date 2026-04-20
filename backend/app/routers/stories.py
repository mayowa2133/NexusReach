"""Story Bank API — reusable proof-points and STAR stories per user."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.stories import StoryCreate, StoryResponse, StoryUpdate
from app.services.story_service import (
    create_story,
    delete_story,
    get_story,
    list_stories,
    update_story,
)

router = APIRouter(prefix="/stories", tags=["stories"])


@router.get("", response_model=list[StoryResponse])
async def list_user_stories(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await list_stories(db, user_id=user_id)


@router.post("", response_model=StoryResponse, status_code=status.HTTP_201_CREATED)
async def create_user_story(
    payload: StoryCreate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await create_story(db, user_id=user_id, payload=payload)


@router.get("/{story_id}", response_model=StoryResponse)
async def get_user_story(
    story_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    story = await get_story(db, user_id=user_id, story_id=story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.patch("/{story_id}", response_model=StoryResponse)
async def update_user_story(
    story_id: uuid.UUID,
    payload: StoryUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    story = await update_story(
        db, user_id=user_id, story_id=story_id, payload=payload
    )
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.delete("/{story_id}")
async def delete_user_story(
    story_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ok = await delete_story(db, user_id=user_id, story_id=story_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"ok": True, "deleted": True}
