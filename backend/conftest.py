"""Shared test fixtures for NexusReach backend tests.

Strategy: Since models use PostgreSQL-specific types (UUID, ARRAY, JSONB),
we mock the service layer for API integration tests rather than using an
in-memory database. Unit tests target pure functions directly.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.dependencies import get_companion_or_user_id, get_current_user_id
from app.middleware.rate_limit import limiter
from app.utils.discovery_rate_limit import check_linkedin_sync_rate_limit

# Deterministic test user
TEST_USER_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


async def _noop_dependency():
    return None


@pytest.fixture
def mock_user_id():
    return TEST_USER_ID


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Keep slowapi state from leaking across tests."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def authed_client(mock_user_id):
    """FastAPI test client with auth bypassed — returns fixed user ID."""

    async def _override_auth():
        return mock_user_id

    app.dependency_overrides[get_current_user_id] = _override_auth
    # Companion-callable endpoints use a dual-auth dependency; bypass it the
    # same way so authed tests cover both paths uniformly.
    app.dependency_overrides[get_companion_or_user_id] = _override_auth
    # The LinkedIn sync limit (6/day) is low enough that repeated local test
    # runs against a live Redis would trip real 429s — no-op it here.
    app.dependency_overrides[check_linkedin_sync_rate_limit] = _noop_dependency
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(authed_client):
    """Async HTTP client for testing API endpoints (auth pre-bypassed)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def unauthed_client(monkeypatch):
    """Async HTTP client with no auth override (for 401 tests)."""
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
