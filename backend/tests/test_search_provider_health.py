"""Search-provider health tracking and beat liveness.

Regression cover for the 2026-07-26 functionality audit: two of three LinkedIn
providers were returning HTTP 400 (revoked key / no credits) and *nothing*
surfaced it — the clients swallowed the error into `[]` and the router logged
`search provider empty`, which is what a genuinely quiet query looks like.
"""

import httpx
import pytest

from app.clients import search_provider_health as sph


# --- evaluate(): telling "broken" apart from "quiet" -----------------------


def test_configured_but_erroring_provider_is_flagged():
    verdicts = sph.evaluate({
        "google_cse": {"hit": 0, "empty": 0, "error": 30, "attempts": 30,
                       "last_error": "HTTP 400: API Key not found"},
    })
    assert verdicts[0]["status"] == "errors"
    assert "API Key not found" in verdicts[0]["last_error"]


def test_provider_that_never_returns_a_result_is_flagged():
    """A polite 200-with-nothing is the case the old INFO log hid."""
    verdicts = sph.evaluate({
        "serper": {"hit": 0, "empty": 40, "error": 0, "attempts": 40, "last_error": None},
    })
    assert verdicts[0]["status"] == "no_results"


def test_a_working_provider_is_not_flagged():
    verdicts = sph.evaluate({
        "brave": {"hit": 18, "empty": 22, "error": 0, "attempts": 40, "last_error": None},
    })
    assert verdicts[0]["status"] == "ok"


def test_one_hit_is_enough_to_clear_a_provider():
    """Most queries legitimately return nothing; only *never* is suspicious."""
    verdicts = sph.evaluate({
        "brave": {"hit": 1, "empty": 39, "error": 0, "attempts": 40, "last_error": None},
    })
    assert verdicts[0]["status"] == "ok"


def test_a_quiet_provider_is_not_judged_too_early():
    verdicts = sph.evaluate({
        "tavily": {"hit": 0, "empty": 3, "error": 0, "attempts": 3, "last_error": None},
    })
    assert verdicts[0]["status"] == "insufficient_data"


# --- fail-soft: visibility must never break a search ----------------------


async def test_record_never_raises_when_redis_is_down(monkeypatch):
    def boom():
        raise RuntimeError("redis down")
    monkeypatch.setattr(sph.search_cache_client, "_client", boom)
    await sph.record("google_cse", "error", detail="x")  # must not raise


async def test_snapshot_returns_empty_when_redis_is_down(monkeypatch):
    def boom():
        raise RuntimeError("redis down")
    monkeypatch.setattr(sph.search_cache_client, "_client", boom)
    assert await sph.snapshot(["google_cse"]) == {}


# --- beat liveness --------------------------------------------------------


async def test_beat_liveness_reports_stale(monkeypatch):
    import time

    class FakeRedis:
        async def get(self, key):
            return str(int(time.time()) - sph.BEAT_STALE_AFTER_SECONDS - 60)
    monkeypatch.setattr(sph.search_cache_client, "_client", lambda: FakeRedis())
    assert (await sph.beat_liveness())["status"] == "stale"


async def test_beat_liveness_reports_ok(monkeypatch):
    import time

    class FakeRedis:
        async def get(self, key):
            return str(int(time.time()) - 60)
    monkeypatch.setattr(sph.search_cache_client, "_client", lambda: FakeRedis())
    assert (await sph.beat_liveness())["status"] == "ok"


async def test_beat_liveness_never_seen(monkeypatch):
    class FakeRedis:
        async def get(self, key):
            return None
    monkeypatch.setattr(sph.search_cache_client, "_client", lambda: FakeRedis())
    assert (await sph.beat_liveness())["status"] == "never_seen"


# --- the clients now report the rejection instead of hiding it ------------


async def test_serper_logs_and_records_a_400(monkeypatch, caplog):
    """'Not enough credits' arrives as 400 — previously swallowed silently."""
    from app.clients import serper_search_client

    monkeypatch.setattr(serper_search_client.settings, "serper_api_key", "k")

    class FakeResponse:
        status_code = 400
        text = '{"message":"Not enough credits","statusCode":400}'

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return FakeResponse()

    recorded = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: FakeClient())
    async def fake_record(provider, outcome, *, detail=None):
        recorded.append((provider, outcome, detail))
    monkeypatch.setattr(serper_search_client.search_provider_health, "record", fake_record)

    with caplog.at_level("WARNING"):
        out = await serper_search_client._run_serper_query("q", 5)

    assert out == []
    assert any("Not enough credits" in r.getMessage() for r in caplog.records), caplog.text
    assert recorded and recorded[0][0] == "serper" and recorded[0][1] == "error"


@pytest.mark.parametrize("status", [400, 403, 429])
async def test_google_cse_reports_every_rejection(monkeypatch, caplog, status):
    """403/429 were handled; 400 (revoked key) fell through and vanished."""
    from app.clients import google_search_client

    monkeypatch.setattr(google_search_client.settings, "google_api_key", "k")
    monkeypatch.setattr(google_search_client.settings, "google_cse_id", "cx")

    class FakeResponse:
        def __init__(self): self.status_code = status
        text = '{"error":{"message":"API Key not found."}}'
        def json(self): return {}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: FakeClient())
    monkeypatch.setattr(google_search_client, "_record_error", lambda *a, **k: None)

    with caplog.at_level("WARNING"):
        out = await google_search_client.search_people("Stripe", titles=["Recruiter"], limit=3)

    assert out == []
    assert any("google_cse rejected" in r.getMessage() for r in caplog.records), caplog.text
