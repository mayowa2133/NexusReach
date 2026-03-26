"""Async pagination helper for SQLAlchemy queries."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select


async def paginate(
    db: AsyncSession,
    query: Select,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list, int]:
    """Apply limit/offset to a query and return ``(items, total_count)``.

    When *limit* is ``None`` the full result set is returned (backward
    compatible).
    """
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    result = await db.execute(query)
    items = list(result.scalars().all())
    return items, total
