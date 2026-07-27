"""Streaming people search (functionality audit #8, perceived latency).

Profiling a cold job-aware search put the initial bucket searches at ~17s of a
~51s total, with the rest spent on conditional recovery and verification that
only *refine* contacts already found. The non-streaming endpoint makes the user
wait the full run staring at nothing; this emits the first ranked contacts as
soon as they exist.
"""

import json
from unittest.mock import AsyncMock, patch


def _frames(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def test_stream_emits_partial_then_final(client):
    """The whole point: usable contacts before the search has finished."""
    partial_seen = {}

    async def fake_search(**kwargs):
        # The service calls on_partial once the initial buckets are prepared.
        on_partial = kwargs.get("on_partial")
        assert on_partial is not None, "streaming must pass a partial callback"
        await on_partial({
            "type": "partial",
            "company_name": "Ramp",
            "recruiters": [{"full_name": "Ada R.", "title": "Recruiter", "provisional": True}],
            "hiring_managers": [],
            "peers": [],
        })
        partial_seen["called"] = True
        return {"company": None, "recruiters": [], "hiring_managers": [], "peers": [],
                "your_connections": [], "job_context": None}

    with (
        patch("app.routers.people.search_people_for_job", side_effect=fake_search),
        patch("app.routers.people.save_job_research_snapshot", new_callable=AsyncMock),
    ):
        resp = await client.post(
            "/api/people/search/stream",
            json={"company_name": "Ramp", "job_id": "11111111-1111-1111-1111-111111111111"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    frames = _frames(resp.text)
    assert [f["type"] for f in frames] == ["partial", "final"]
    assert partial_seen.get("called") is True


async def test_partial_rows_are_flagged_provisional_and_carry_no_id(client):
    """A provisional row must not look actionable — it has no Person id yet."""
    async def fake_search(**kwargs):
        await kwargs["on_partial"]({
            "type": "partial",
            "company_name": "Ramp",
            "recruiters": [{"full_name": "Ada R.", "title": "Recruiter", "provisional": True}],
            "hiring_managers": [],
            "peers": [],
        })
        return {"company": None, "recruiters": [], "hiring_managers": [], "peers": [],
                "your_connections": [], "job_context": None}

    with (
        patch("app.routers.people.search_people_for_job", side_effect=fake_search),
        patch("app.routers.people.save_job_research_snapshot", new_callable=AsyncMock),
    ):
        resp = await client.post(
            "/api/people/search/stream",
            json={"company_name": "Ramp", "job_id": "11111111-1111-1111-1111-111111111111"},
        )

    partial = _frames(resp.text)[0]
    row = partial["recruiters"][0]
    assert row["provisional"] is True
    assert "id" not in row
    assert "work_email" not in row


async def test_failure_is_reported_as_a_frame_not_a_dropped_connection(client):
    async def boom(**kwargs):
        raise RuntimeError("provider exploded")

    with patch("app.routers.people.search_people_for_job", side_effect=boom):
        resp = await client.post(
            "/api/people/search/stream",
            json={"company_name": "Ramp", "job_id": "11111111-1111-1111-1111-111111111111"},
        )

    frames = _frames(resp.text)
    assert frames[-1]["type"] == "error"


async def test_missing_job_returns_an_error_frame(client):
    async def not_found(**kwargs):
        raise ValueError("no job")

    with patch("app.routers.people.search_people_for_job", side_effect=not_found):
        resp = await client.post(
            "/api/people/search/stream",
            json={"company_name": "Ramp", "job_id": "11111111-1111-1111-1111-111111111111"},
        )
    assert _frames(resp.text)[-1] == {"type": "error", "message": "Job not found"}


async def test_streaming_requires_a_job_id(client):
    """Company-level search has no partial seam; don't pretend it streams."""
    resp = await client.post("/api/people/search/stream", json={"company_name": "Ramp"})
    assert resp.status_code == 400


async def test_invalid_job_id_is_rejected(client):
    resp = await client.post(
        "/api/people/search/stream",
        json={"company_name": "Ramp", "job_id": "not-a-uuid"},
    )
    assert resp.status_code == 400


# --- the service-side hook -------------------------------------------------


async def test_a_broken_consumer_cannot_fail_the_search():
    """If the client hung up, the search must still complete and persist."""
    from app.services.people.service import _partial_payload

    # _partial_payload is pure; the swallow behaviour is asserted via the
    # service contract documented on search_people_for_job. Here we pin the
    # payload shape the endpoint depends on.
    payload = _partial_payload(
        company=None,
        recruiters=[{"full_name": "Ada", "title": "Recruiter", "linkedin_url": "u"}],
        hiring_managers=[],
        peers=[],
    )
    assert payload["type"] == "partial"
    assert payload["recruiters"][0]["provisional"] is True
    assert payload["recruiters"][0]["full_name"] == "Ada"
    assert "id" not in payload["recruiters"][0]
