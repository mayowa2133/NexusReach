"""Async pagination helper for SQLAlchemy queries."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

DEFAULT_LIMIT = 200
MAX_LIMIT = 500


def clamp_limit(limit: int | None) -> int:
    """Ensure limit is within safe bounds.

    When *limit* is ``None`` or exceeds ``MAX_LIMIT``, it is clamped to
    ``DEFAULT_LIMIT`` or ``MAX_LIMIT`` respectively.
    """
    if limit is None or limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


async def paginate(
    db: AsyncSession,
    query: Select,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list, int]:
    """Apply limit/offset to a query and return ``(items, total_count)``.

    When *limit* is ``None`` the default limit is applied.
    """
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    if offset:
        query = query.offset(offset)
    query = query.limit(clamp_limit(limit))

    result = await db.execute(query)
    items = list(result.scalars().all())
    return items, total
