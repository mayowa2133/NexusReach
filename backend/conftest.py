"""Shared test fixtures for NexusReach backend tests.

Strategy: Since models use PostgreSQL-specific types (UUID, ARRAY, JSONB),
we mock the service layer for API integration tests rather than using an
in-memory database. Unit tests target pure functions directly.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.dependencies import get_current_user_id

# Deterministic test user
TEST_USER_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def mock_user_id():
    return TEST_USER_ID


@pytest.fixture
def authed_client(mock_user_id):
    """FastAPI test client with auth bypassed — returns fixed user ID."""

    async def _override_auth():
        return mock_user_id

    app.dependency_overrides[get_current_user_id] = _override_auth
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(authed_client):
    """Async HTTP client for testing API endpoints (auth pre-bypassed)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def unauthed_client():
    """Async HTTP client with no auth override (for 401 tests)."""
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
