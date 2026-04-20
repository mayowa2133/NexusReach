"""CRUD service for the user-owned Story Bank."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story import Story
from app.schemas.stories import StoryCreate, StoryUpdate


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            continue
        tag = raw.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


async def list_stories(db: AsyncSession, *, user_id: uuid.UUID) -> list[Story]:
    result = await db.execute(
        select(Story).where(Story.user_id == user_id).order_by(Story.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_story(
    db: AsyncSession, *, user_id: uuid.UUID, story_id: uuid.UUID
) -> Story | None:
    result = await db.execute(
        select(Story).where(Story.id == story_id, Story.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_story(
    db: AsyncSession, *, user_id: uuid.UUID, payload: StoryCreate
) -> Story:
    story = Story(
        user_id=user_id,
        title=payload.title.strip(),
        summary=payload.summary,
        situation=payload.situation,
        action=payload.action,
        result=payload.result,
        impact_metric=payload.impact_metric,
        role_focus=payload.role_focus,
        tags=_normalize_tags(payload.tags),
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    return story


async def update_story(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    story_id: uuid.UUID,
    payload: StoryUpdate,
) -> Story | None:
    story = await get_story(db, user_id=user_id, story_id=story_id)
    if story is None:
        return None

    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        story.title = data["title"].strip()
    for field in ("summary", "situation", "action", "result", "impact_metric", "role_focus"):
        if field in data:
            setattr(story, field, data[field])
    if "tags" in data:
        story.tags = _normalize_tags(data["tags"])

    await db.commit()
    await db.refresh(story)
    return story


async def delete_story(
    db: AsyncSession, *, user_id: uuid.UUID, story_id: uuid.UUID
) -> bool:
    story = await get_story(db, user_id=user_id, story_id=story_id)
    if story is None:
        return False
    await db.delete(story)
    await db.commit()
    return True


async def find_relevant_stories(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    role_focus: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
) -> list[Story]:
    """Best-effort relevance: tag overlap or role substring, fall back to recent.

    Used by drafting to inject candidate proof points without requiring an LLM
    relevance pass.
    """
    stories = await list_stories(db, user_id=user_id)
    if not stories:
        return []

    wanted_tags = {t.lower() for t in (tags or []) if isinstance(t, str)}
    role_lower = (role_focus or "").lower().strip()

    def score(story: Story) -> int:
        s = 0
        story_tags = {t.lower() for t in (story.tags or []) if isinstance(t, str)}
        if wanted_tags & story_tags:
            s += 10 * len(wanted_tags & story_tags)
        if role_lower and story.role_focus and role_lower in story.role_focus.lower():
            s += 5
        return s

    ranked = sorted(stories, key=lambda s: (score(s), s.updated_at), reverse=True)
    if any(score(s) > 0 for s in ranked):
        ranked = [s for s in ranked if score(s) > 0]
    return ranked[:limit]
