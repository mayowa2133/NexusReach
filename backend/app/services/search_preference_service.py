"""Search preference service — manage saved search preferences."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_preference import SearchPreference


async def get_search_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[SearchPreference]:
    """List all search preferences for a user."""
    stmt = (
        select(SearchPreference)
        .where(SearchPreference.user_id == user_id)
        .order_by(SearchPreference.updated_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def toggle_search_preference(
    db: AsyncSession,
    user_id: uuid.UUID,
    pref_id: uuid.UUID,
    enabled: bool,
) -> SearchPreference:
    """Enable or disable a search preference."""
    stmt = select(SearchPreference).where(
        SearchPreference.id == pref_id,
        SearchPreference.user_id == user_id,
    )
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()
    if not pref:
        raise ValueError("Search preference not found")
    pref.enabled = enabled
    await db.commit()
    await db.refresh(pref)
    return pref


async def delete_search_preference(
    db: AsyncSession,
    user_id: uuid.UUID,
    pref_id: uuid.UUID,
) -> None:
    """Delete a search preference."""
    stmt = select(SearchPreference).where(
        SearchPreference.id == pref_id,
        SearchPreference.user_id == user_id,
    )
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()
    if not pref:
        raise ValueError("Search preference not found")
    await db.delete(pref)
    await db.commit()
