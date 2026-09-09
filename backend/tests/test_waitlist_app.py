"""Contracts for the deliberately small public prelaunch application."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_waitlist_app_exposes_only_prelaunch_routes():
    from app.waitlist_app import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        health = await client.get("/api/health")
        waitlist = await client.post("/api/waitlist", json={})
        referral = await client.get("/api/referrals/status")
        occupations = await client.get("/api/occupations")
        jobs = await client.get("/api/jobs")
        people = await client.post("/api/people/search", json={})
        schema = await client.get("/openapi.json")

    assert health.status_code == 200
    assert waitlist.status_code == 422
    assert referral.status_code == 422
    assert occupations.status_code == 200
    assert len(occupations.json()) > 0
    assert {"key", "label"} <= occupations.json()[0].keys()
    assert jobs.status_code == 404
    assert people.status_code == 404
    assert schema.status_code == 404
