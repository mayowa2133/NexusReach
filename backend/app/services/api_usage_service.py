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
) -> ApiUsage:
    """Record an external API call for the user."""
    record = ApiUsage(
        user_id=user_id,
        service=service,
        endpoint=endpoint,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_cents=cost_cents,
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
        "daily_token_limit": settings.daily_claude_token_limit,
        "calls_remaining": max(0, settings.daily_api_call_limit - total_calls),
        "tokens_remaining": max(0, settings.daily_claude_token_limit - total_tokens),
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
    if total_tokens >= settings.daily_claude_token_limit:
        raise ValueError(
            f"Daily token limit reached ({settings.daily_claude_token_limit:,} tokens). "
            "Try again tomorrow."
        )

    return True
