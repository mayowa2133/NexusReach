"""Regression tests for pre-parse request body limits."""

import pytest

from app.config import settings


pytestmark = pytest.mark.asyncio


async def test_public_waitlist_rejects_oversized_body_before_validation(unauthed_client):
    # The waitlist carries an optional base64 resume, so it has its own larger
    # route limit (max_waitlist_request_bytes) rather than the JSON default.
    response = await unauthed_client.post(
        "/api/waitlist",
        content=b"x" * (settings.max_waitlist_request_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "HTTP_413"


async def test_public_waitlist_allows_body_above_default_json_limit(unauthed_client):
    """A body over the 1 MiB JSON default must reach routing, not 413 early.

    Guards the resume-upload path: it only needs to get past the size middleware
    here (an unparseable body then fails validation, which is fine).
    """
    response = await unauthed_client.post(
        "/api/waitlist",
        content=b"x" * (settings.max_request_body_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code != 413


async def test_resume_json_uses_its_route_specific_limit(client):
    response = await client.post(
        "/api/profile/resume-json",
        content=b"x" * (settings.max_resume_json_request_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
