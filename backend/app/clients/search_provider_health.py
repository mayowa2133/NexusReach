"""Per-provider health tracking for the search router.

Why this exists: on 2026-07-26 an audit found Google CSE returning HTTP 400
("API Key not found") and Serper returning HTTP 400 ("Not enough credits") — for
an unknown length of time. Every LinkedIn discovery query in the product was
being served by the third provider in the chain, the one documented as having
the weakest LinkedIn recall, and *nothing surfaced that*. The clients caught the
error and returned ``[]``; the router logged ``search provider empty`` at INFO,
which is indistinguishable from "this query genuinely had no results".

The fallback chain is doing its job by masking the outage. That is exactly why
it needs telemetry on top: a broken credential looks identical to a quiet query
unless someone counts.

Design mirrors ``jobs.storage.evaluate_source_health``: record cheap per-outcome
counters, then let a scheduled task escalate a *sustained* pattern to one
aggregated ERROR (Sentry dedupes it into a single rising issue) rather than
alerting on every blip.

Everything here is fail-soft. Health accounting must never break a search: if
Redis is unavailable we simply lose visibility, which is where we started.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from app.clients import search_cache_client

logger = logging.getLogger(__name__)

Outcome = Literal["hit", "empty", "error"]

# Rolling window. Long enough that a handful of genuinely empty queries can't
# trip an alert, short enough that a revoked key is caught the same day.
WINDOW_SECONDS = 6 * 60 * 60

# Don't judge a provider until it has had a fair number of chances.
MIN_ATTEMPTS = 12

# A configured provider that never once returned results across this share of
# a full window is not "unlucky", it is broken.
ZERO_RESULT_THRESHOLD = 1.0

_KEY_PREFIX = "search_health"


def _bucket(now: float | None = None) -> int:
    """Hour bucket, so counters expire naturally instead of growing forever."""
    return int((now if now is not None else time.time()) // 3600)


async def record(provider: str, outcome: Outcome, *, detail: str | None = None) -> None:
    """Count one provider call. Never raises."""
    try:
        client = search_cache_client._client()
        key = f"{_KEY_PREFIX}:{provider}:{_bucket()}"
        pipe = client.pipeline()
        pipe.hincrby(key, outcome, 1)
        # Keep the most recent error message so the alert can say *why*.
        if outcome == "error" and detail:
            pipe.hset(key, "last_error", detail[:300])
        pipe.expire(key, WINDOW_SECONDS + 3600)
        await pipe.execute()
    except Exception:  # visibility is optional; the search is not
        logger.debug("search provider health: could not record %s", provider, exc_info=True)


async def snapshot(providers: list[str]) -> dict[str, dict]:
    """Aggregate each provider's counters across the window."""
    out: dict[str, dict] = {}
    try:
        client = search_cache_client._client()
    except Exception:
        logger.debug("search provider health: redis unavailable", exc_info=True)
        return out

    current = _bucket()
    buckets = range(current - (WINDOW_SECONDS // 3600), current + 1)
    for provider in providers:
        totals = {"hit": 0, "empty": 0, "error": 0, "last_error": None}
        for b in buckets:
            try:
                raw = await client.hgetall(f"{_KEY_PREFIX}:{provider}:{b}")
            except Exception:
                continue
            if not raw:
                continue
            for field in ("hit", "empty", "error"):
                value = raw.get(field) or raw.get(field.encode()) if isinstance(raw, dict) else None
                if value is not None:
                    try:
                        totals[field] += int(value)
                    except (TypeError, ValueError):
                        pass
            err = raw.get("last_error") or raw.get(b"last_error")
            if err:
                totals["last_error"] = err.decode() if isinstance(err, bytes) else err
        totals["attempts"] = totals["hit"] + totals["empty"] + totals["error"]
        out[provider] = totals
    return out


def evaluate(health: dict[str, dict]) -> list[dict]:
    """Return one verdict per provider, flagging the ones that look broken.

    Two distinct failure shapes, because they need different fixes:

    * ``errors`` — the provider is returning HTTP errors (revoked key, quota,
      outage). Actionable immediately, and the recorded message usually says
      exactly what to do.
    * ``no_results`` — the provider answers 200 but has never once returned a
      result across a full window. That is what an exhausted-but-polite API or
      a misconfigured search engine ID looks like, and it is the case the old
      INFO log made invisible.
    """
    verdicts: list[dict] = []
    for provider, t in health.items():
        attempts = t.get("attempts", 0)
        if attempts < MIN_ATTEMPTS:
            verdicts.append({"provider": provider, "status": "insufficient_data", **t})
            continue
        if t.get("error", 0) and t.get("hit", 0) == 0:
            status = "errors"
        elif t.get("hit", 0) == 0 and (t.get("empty", 0) / attempts) >= ZERO_RESULT_THRESHOLD:
            status = "no_results"
        else:
            status = "ok"
        verdicts.append({"provider": provider, "status": status, **t})
    return verdicts


# --- Celery beat liveness --------------------------------------------------
#
# Beat has quietly become load-bearing for two user-visible guarantees:
# occupation tagging (`retag-occupation-tags` heals the feed's targeting) and
# data retention (`purge-waitlist-pii` expires resumes and IPs). If beat stops,
# neither fails loudly — targeting silently narrows and PII silently persists.
# A heartbeat makes "beat is alive" answerable without shelling into Railway.

_BEAT_HEARTBEAT_KEY = f"{_KEY_PREFIX}:beat_heartbeat"

# Beat's shortest interval is every 5 minutes, so anything past ~30 means it is
# not running rather than merely between ticks.
BEAT_STALE_AFTER_SECONDS = 30 * 60


async def record_beat_heartbeat() -> None:
    """Stamp 'beat ran just now'. Never raises."""
    try:
        client = search_cache_client._client()
        await client.set(_BEAT_HEARTBEAT_KEY, str(int(time.time())), ex=7 * 24 * 3600)
    except Exception:
        logger.debug("beat heartbeat: could not record", exc_info=True)


async def beat_liveness() -> dict:
    """Age of the last beat tick, for the readiness probe."""
    try:
        client = search_cache_client._client()
        raw = await client.get(_BEAT_HEARTBEAT_KEY)
    except Exception:
        return {"status": "unknown", "age_seconds": None}
    if not raw:
        return {"status": "never_seen", "age_seconds": None}
    try:
        age = int(time.time()) - int(raw)
    except (TypeError, ValueError):
        return {"status": "unknown", "age_seconds": None}
    return {
        "status": "ok" if age <= BEAT_STALE_AFTER_SECONDS else "stale",
        "age_seconds": age,
    }
