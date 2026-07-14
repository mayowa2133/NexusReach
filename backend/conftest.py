"""Shared test fixtures for NexusReach backend tests.

Strategy: Since models use PostgreSQL-specific types (UUID, ARRAY, JSONB),
we mock the service layer for API integration tests rather than using an
in-memory database. Unit tests target pure functions directly.
"""

# ruff: noqa: E402 -- test environment must be sealed before app imports

import os
import uuid

# Unit/API tests must never inherit production-like connection strings or
# credentials from a developer's ignored ``backend/.env``. Unexpected database
# access fails immediately on the discard port instead of reaching Supabase;
# focused integration tests create and bind their own engines explicitly.
os.environ["NEXUSREACH_ENVIRONMENT"] = "test"
os.environ["NEXUSREACH_DATABASE_URL"] = (
    "postgresql+asyncpg://nexusreach_test:nexusreach_test@127.0.0.1:1/nexusreach_test"
)
os.environ["NEXUSREACH_REDIS_URL"] = "redis://127.0.0.1:1/15"
for _secret_name in (
    "SUPABASE_JWT_SECRET",
    "SUPABASE_SERVICE_ROLE_KEY",
    "WAITLIST_ADMIN_TOKEN",
    "APOLLO_API_KEY",
    "APOLLO_MASTER_API_KEY",
    "HUNTER_API_KEY",
    "GITHUB_TOKEN",
    "JSEARCH_API_KEY",
    "ADZUNA_API_KEY",
    "DICE_API_KEY",
    "USAJOBS_API_KEY",
    "THEMUSE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "BRAVE_API_KEY",
    "SERPER_API_KEY",
    "TAVILY_API_KEY",
    "YOUCOM_API_KEY",
    "EXA_API_KEY",
    "FIRECRAWL_API_KEY",
    "SCRAPEGRAPH_API_KEY",
    "GOOGLE_CLIENT_SECRET",
    "MICROSOFT_CLIENT_SECRET",
    "SENTRY_DSN",
    "POSTHOG_API_KEY",
    "READINESS_TOKEN",
):
    os.environ[f"NEXUSREACH_{_secret_name}"] = ""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.dependencies import get_current_user_id
from app.middleware.rate_limit import limiter

# Deterministic test user
TEST_USER_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


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
