"""Fail-closed, atomic deployment-wide resource admission in Redis."""

import hashlib
import time
import uuid
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import HTTPException

from app.config import settings
from app.utils.discovery_rate_limit import _client

_CONSUME = """
for i, key in ipairs(KEYS) do
  local amount = tonumber(ARGV[2*i])
  local cap = tonumber(ARGV[2*i+1])
  if amount < 0 or cap <= 0 or tonumber(redis.call('GET', key) or '0') + amount > cap then
    return 0
  end
end
for i, key in ipairs(KEYS) do
  redis.call('INCRBY', key, ARGV[2*i])
  redis.call('EXPIRE', key, ARGV[1])
end
return 1
"""

_ACQUIRE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2])/1000000
for i, key in ipairs(KEYS) do
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
  if tonumber(ARGV[i+2]) <= 0 or redis.call('ZCARD', key) >= tonumber(ARGV[i+2]) then
    return 0
  end
end
for _, key in ipairs(KEYS) do
  redis.call('ZADD', key, now+tonumber(ARGV[2]), ARGV[1])
  redis.call('EXPIRE', key, math.ceil(tonumber(ARGV[2]))+60)
end
return 1
"""


def identity_key(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


async def consume(limits: list[tuple[str, int, int]], *, window: int = 86400) -> None:
    """Charge all (name, cap, amount) limits before work, or charge none.

    Failed/unknown work is deliberately not refunded. This is a hard allowance,
    not a promise to maximize throughput during provider or broker failures.
    """
    if settings.environment in {"test", "e2e"}:
        return
    period = int(time.time()) // window
    keys = [f"nr:resource:{name}:{period}" for name, _, _ in limits]
    values = [value for _, cap, amount in limits for value in (amount, cap)]
    try:
        accepted = await _client().eval(_CONSUME, len(keys), *keys, window + 60, *values)
    except Exception:
        raise HTTPException(503, "Resource admission is temporarily unavailable.") from None
    if accepted != 1:
        raise HTTPException(429, "This action's shared allowance is exhausted. Try later.",
                            headers={"Retry-After": str(window)})


@asynccontextmanager
async def process_capacity(timeout_seconds: float) -> AsyncIterator[None]:
    """Share one finite child-process budget across API and Celery workers."""
    if settings.environment in {"test", "e2e"}:
        yield
        return
    from app.services.paid_context import get_subject

    subject = str(get_subject() or "public")
    keys = ["nr:process:global", f"nr:process:account:{subject}"]
    token = uuid.uuid4().hex
    try:
        redis = _client()
        accepted = await redis.eval(
            _ACQUIRE, 2, *keys, token, timeout_seconds + 10,
            settings.parser_global_concurrency, settings.parser_account_concurrency,
        )
    except Exception:
        raise HTTPException(503, "Document processing capacity is unavailable.") from None
    if accepted != 1:
        raise HTTPException(429, "Document processing is busy. Try shortly.", headers={"Retry-After": "5"})
    try:
        yield
    finally:
        try:
            for key in keys:
                await redis.zrem(key, token)
        except Exception:
            # The lease outlives the hard process deadline and expires safely.
            logging.getLogger(__name__).warning("Could not release process capacity lease")
