"""API usage tracking service — records consumption, checks daily limits."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.api_usage import ApiUsage


async def record_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    service: str,
    endpoint: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_cents: int | None = None,
    credits_used: float | None = None,
    details: dict | None = None,
) -> ApiUsage:
    """Record an external API call for the user."""
    record = ApiUsage(
        user_id=user_id,
        service=service,
        endpoint=endpoint,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_cents=cost_cents,
        credits_used=credits_used,
        details=details,
    )
    db.add(record)
    await db.flush()
    return record


async def get_daily_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    service: str | None = None,
) -> dict:
    """Get today's usage summary for a user, optionally filtered by service."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    query = select(
        func.count(ApiUsage.id).label("total_calls"),
        func.coalesce(func.sum(ApiUsage.tokens_in), 0).label("total_tokens_in"),
        func.coalesce(func.sum(ApiUsage.tokens_out), 0).label("total_tokens_out"),
        func.coalesce(func.sum(ApiUsage.cost_cents), 0).label("total_cost_cents"),
    ).where(
        ApiUsage.user_id == user_id,
        ApiUsage.created_at >= today_start,
    )

    if service:
        query = query.where(ApiUsage.service == service)

    result = await db.execute(query)
    row = result.one()

    total_calls = row.total_calls
    total_tokens = row.total_tokens_in + row.total_tokens_out

    return {
        "total_calls": total_calls,
        "total_tokens_in": row.total_tokens_in,
        "total_tokens_out": row.total_tokens_out,
        "total_cost_cents": row.total_cost_cents,
        "daily_call_limit": settings.daily_api_call_limit,
        "daily_token_limit": settings.daily_llm_token_limit,
        "calls_remaining": max(0, settings.daily_api_call_limit - total_calls),
        "tokens_remaining": max(0, settings.daily_llm_token_limit - total_tokens),
    }


async def check_daily_limit(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> bool:
    """Check if user is within daily limits. Returns True if OK.

    Raises ValueError if over any limit.
    """
    usage = await get_daily_usage(db, user_id)

    if usage["calls_remaining"] <= 0:
        raise ValueError(
            f"Daily API call limit reached ({settings.daily_api_call_limit} calls). "
            "Try again tomorrow."
        )

    total_tokens = usage["total_tokens_in"] + usage["total_tokens_out"]
    if total_tokens >= settings.daily_llm_token_limit:
        raise ValueError(
            f"Daily token limit reached ({settings.daily_llm_token_limit:,} tokens). "
            "Try again tomorrow."
        )

    return True


async def get_monthly_usage_count(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    service: str,
    endpoint_prefix: str | None = None,
) -> int:
    """Get the current month's usage count for a service, optionally by endpoint prefix."""
    month_start = datetime.now(timezone.utc).replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    query = select(func.count(ApiUsage.id)).where(
        ApiUsage.user_id == user_id,
        ApiUsage.service == service,
        ApiUsage.created_at >= month_start,
    )
    if endpoint_prefix:
        query = query.where(ApiUsage.endpoint.like(f"{endpoint_prefix}%"))

    result = await db.execute(query)
    return int(result.scalar() or 0)


async def has_monthly_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    service: str,
    endpoint: str,
) -> bool:
    """Return True if the exact service+endpoint has been used this calendar month."""
    month_start = datetime.now(timezone.utc).replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    query = select(ApiUsage.id).where(
        ApiUsage.user_id == user_id,
        ApiUsage.service == service,
        ApiUsage.endpoint == endpoint,
        ApiUsage.created_at >= month_start,
    ).limit(1)
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


async def get_usage_records(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    service: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
) -> list[ApiUsage]:
    """Return usage records ordered newest-first for auditing."""
    query = select(ApiUsage).where(ApiUsage.user_id == user_id)

    if service:
        query = query.where(ApiUsage.service == service)
    if date_from:
        query = query.where(ApiUsage.created_at >= date_from)
    if date_to:
        query = query.where(ApiUsage.created_at <= date_to)

    query = query.order_by(ApiUsage.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
