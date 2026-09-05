"""Atomic reservations for every externally billed provider invocation."""

from __future__ import annotations

import logging
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, text

from app.config import settings
from app.database import async_session
from app.models.paid_work import PaidBudgetBucket, PaidReservation

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _retry_after(now: datetime) -> str:
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time(), timezone.utc)
    return str(max(1, int((tomorrow - now).total_seconds())))


async def _lock(db, key: str) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": key},
    )


async def _bucket(
    db, *, scope: str, period, user_id: uuid.UUID | None
) -> PaidBudgetBucket:
    row = (
        await db.execute(
            select(PaidBudgetBucket)
            .where(PaidBudgetBucket.scope == scope, PaidBudgetBucket.period == period)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = PaidBudgetBucket(scope=scope, period=period, user_id=user_id)
        db.add(row)
        await db.flush()
    return row


def _check_capacity(
    bucket: PaidBudgetBucket,
    *,
    call_limit: int,
    token_limit: int,
    concurrency_limit: int,
    tokens: int,
    now: datetime,
) -> None:
    if bucket.calls_settled + bucket.calls_reserved + 1 > call_limit:
        raise HTTPException(
            429,
            "Paid-work call budget exhausted.",
            headers={"Retry-After": _retry_after(now)},
        )
    if bucket.tokens_settled + bucket.tokens_reserved + tokens > token_limit:
        raise HTTPException(
            429,
            "Paid-work token budget exhausted.",
            headers={"Retry-After": _retry_after(now)},
        )
    if bucket.active_operations + 1 > concurrency_limit:
        raise HTTPException(
            429,
            "Too many paid operations are already running.",
            headers={"Retry-After": "5"},
        )


async def reserve(
    *,
    user_id: uuid.UUID,
    operation_id: str,
    service: str,
    reserved_tokens: int = 0,
) -> PaidReservation | None:
    """Reserve account and global capacity and commit before provider I/O."""
    if settings.environment in {"test", "e2e"}:
        return None
    if not operation_id or len(operation_id) > 160:
        raise HTTPException(503, "Paid-work reservation could not be established.")

    now = _now()
    period = now.date()
    tokens = max(0, int(reserved_tokens))
    try:
        async with async_session() as db:
            # A stable operation id makes queue redelivery reuse the reservation.
            existing = await db.get(PaidReservation, operation_id)
            if existing is not None:
                if existing.user_id != user_id or existing.service != service:
                    raise HTTPException(409, "Paid-work operation id is already in use.")
                return existing

            # Global then account is the only lock order used by this service.
            await _lock(db, f"paid:global:{period.isoformat()}")
            await _lock(db, f"paid:account:{user_id}:{period.isoformat()}")
            global_bucket = await _bucket(
                db, scope="global", period=period, user_id=None
            )
            account_bucket = await _bucket(
                db, scope=f"account:{user_id}", period=period, user_id=user_id
            )
            _check_capacity(
                global_bucket,
                call_limit=settings.global_daily_api_call_limit,
                token_limit=settings.global_daily_llm_token_limit,
                concurrency_limit=settings.global_paid_concurrency,
                tokens=tokens,
                now=now,
            )
            _check_capacity(
                account_bucket,
                call_limit=settings.daily_api_call_limit,
                token_limit=settings.daily_llm_token_limit,
                concurrency_limit=settings.account_paid_concurrency,
                tokens=tokens,
                now=now,
            )
            for bucket in (global_bucket, account_bucket):
                bucket.calls_reserved += 1
                bucket.tokens_reserved += tokens
                bucket.active_operations += 1
            row = PaidReservation(
                operation_id=operation_id,
                user_id=user_id,
                service=service,
                period=period,
                reserved_tokens=tokens,
                state="reserved",
                expires_at=now + timedelta(seconds=settings.paid_reservation_ttl_seconds),
            )
            db.add(row)
            await db.commit()
            return row
    except HTTPException:
        raise
    except Exception:
        logger.error("Paid-work reservation database unavailable", exc_info=True)
        raise HTTPException(
            503, "Paid-work reservation could not be established."
        ) from None


@asynccontextmanager
async def provider_call(service: str, *, operation_id: str | None = None):
    """Guard one non-LLM provider request with the same durable accounting."""
    from app.services.paid_context import get_subject, operation_id as make_operation_id

    subject = get_subject()
    if subject is None and settings.environment not in {"test", "e2e"}:
        raise HTTPException(503, "Paid-work account context is unavailable.")
    call_id = operation_id or make_operation_id(f"provider:{service}")
    reservation = None
    if subject is not None:
        reservation = await reserve(
            user_id=subject,
            operation_id=call_id,
            service=service,
        )
    if reservation is not None and reservation.state != "reserved":
        raise HTTPException(409, "Paid-work operation has already been dispatched.")
    try:
        await mark_dispatched(call_id)
    except Exception:
        # No external request occurred, so this reservation is safe to release.
        await release(call_id)
        raise
    try:
        yield
    except Exception:
        await mark_unknown(call_id)
        raise
    else:
        await settle(call_id, 0)


async def provider_request(client, service: str, method: str, url: str, **kwargs):
    """Issue one HTTP request only after its durable reservation commits."""
    from app.services.paid_context import operation_id

    request_shape = {
        "method": method.upper(),
        "url": url,
        # Headers contain provider credentials and do not define logical work.
        "params": kwargs.get("params"),
        "json": kwargs.get("json"),
        "data": kwargs.get("data"),
        "content": kwargs.get("content"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(request_shape, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    call_id = operation_id(f"provider:{service}", fingerprint)
    async with provider_call(service, operation_id=call_id):
        request = getattr(client, method.lower(), None)
        if request is None:
            request = client.request
            return await request(method, url, **kwargs)
        return await request(url, **kwargs)


async def mark_dispatched(operation_id: str) -> None:
    if settings.environment in {"test", "e2e"}:
        return
    async with async_session() as db:
        row = await db.get(PaidReservation, operation_id, with_for_update=True)
        if row is None or row.state != "reserved":
            raise HTTPException(409, "Paid-work operation is not dispatchable.")
        row.state = "dispatched"
        row.dispatched_at = _now()
        await db.commit()


async def _finish(operation_id: str, *, state: str, actual_tokens: int | None) -> None:
    if settings.environment in {"test", "e2e"}:
        return
    async with async_session() as db:
        row = await db.get(PaidReservation, operation_id, with_for_update=True)
        if row is None or row.state not in {"reserved", "dispatched"}:
            return
        period = row.period
        await _lock(db, f"paid:global:{period.isoformat()}")
        await _lock(db, f"paid:account:{row.user_id}:{period.isoformat()}")
        buckets = (
            await db.execute(
                select(PaidBudgetBucket)
                .where(
                    PaidBudgetBucket.period == period,
                    PaidBudgetBucket.scope.in_(["global", f"account:{row.user_id}"]),
                )
                .with_for_update()
            )
        ).scalars().all()
        for bucket in buckets:
            bucket.active_operations = max(0, bucket.active_operations - 1)
            if state == "settled":
                bucket.calls_reserved = max(0, bucket.calls_reserved - 1)
                bucket.tokens_reserved = max(
                    0, bucket.tokens_reserved - row.reserved_tokens
                )
                bucket.calls_settled += 1
                bucket.tokens_settled += max(0, int(actual_tokens or 0))
            elif state == "released":
                bucket.calls_reserved = max(0, bucket.calls_reserved - 1)
                bucket.tokens_reserved = max(
                    0, bucket.tokens_reserved - row.reserved_tokens
                )
            # Unknown dispatched work remains charged conservatively.
        row.state = state
        row.actual_tokens = actual_tokens
        row.completed_at = _now()
        await db.commit()


async def settle(operation_id: str, actual_tokens: int) -> None:
    await _finish(operation_id, state="settled", actual_tokens=actual_tokens)


async def mark_unknown(operation_id: str) -> None:
    await _finish(operation_id, state="unknown", actual_tokens=None)


async def release(operation_id: str) -> None:
    """Release only work that was reserved but never dispatched."""
    await _finish(operation_id, state="released", actual_tokens=0)


async def recover_expired() -> dict[str, int]:
    """Release expired pre-dispatch claims and quarantine dispatched claims."""
    if settings.environment in {"test", "e2e"}:
        return {"released": 0, "unknown": 0}
    now = _now()
    async with async_session() as db:
        ids = list(
            await db.scalars(
                select(PaidReservation.operation_id).where(
                    PaidReservation.state.in_(["reserved", "dispatched"]),
                    PaidReservation.expires_at <= now,
                )
            )
        )
    counts = {"released": 0, "unknown": 0}
    for operation_id in ids:
        async with async_session() as db:
            state = await db.scalar(
                select(PaidReservation.state).where(
                    PaidReservation.operation_id == operation_id
                )
            )
        if state == "reserved":
            await release(operation_id)
            counts["released"] += 1
        elif state == "dispatched":
            await mark_unknown(operation_id)
            counts["unknown"] += 1
    return counts
