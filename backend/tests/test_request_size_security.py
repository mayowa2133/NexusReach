"""Regression tests for pre-parse request body limits."""

import pytest

from app.config import settings


pytestmark = pytest.mark.asyncio


async def test_public_waitlist_rejects_oversized_body_before_validation(unauthed_client):
    response = await unauthed_client.post(
        "/api/waitlist",
        content=b"x" * (settings.max_request_body_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "HTTP_413"


async def test_resume_json_uses_its_route_specific_limit(client):
    response = await client.post(
        "/api/profile/resume-json",
        content=b"x" * (settings.max_resume_json_request_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
