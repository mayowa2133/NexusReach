from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.middleware.demo_mode import blocked_demo_action
from scripts.demo_reset import demo_uuid, seed_returning_fixture


def safe_demo_settings(**overrides) -> dict:
    values = {
        "environment": "e2e",
        "demo_mode": True,
        "database_url": "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/nexusreach_e2e",
        "redis_url": "redis://127.0.0.1:6381/15",
        "auth_mode": "dev",
        "dev_auth_bypass_enabled": True,
        "employment_verify_enabled": False,
        "theorg_traversal_enabled": False,
        "jina_reader_enabled": False,
    }
    values.update(overrides)
    return values


def test_demo_config_accepts_only_safe_local_environment():
    parsed = Settings(_env_file=None, **safe_demo_settings())
    assert parsed.demo_mode is True


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"database_url": "postgresql+asyncpg://user:pass@db.example.com/nexusreach_e2e"}, "loopback"),
        ({"database_url": "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/nexusreach"}, "e2e or demo"),
        ({"redis_url": "redis://redis.example.com:6379/0"}, "loopback"),
        ({"auth_mode": "supabase"}, "AUTH_MODE=dev"),
        ({"openai_api_key": "should-not-load"}, "OPENAI_API_KEY must be empty"),
        ({"environment": "development"}, "must be e2e"),
        ({"jina_reader_enabled": True}, "JINA_READER_ENABLED must be false"),
    ],
)
def test_demo_config_rejects_unsafe_environment(override, message):
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **safe_demo_settings(**override))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/jobs/discover"),
        ("POST", "/api/jobs/ensure-fresh"),
        ("POST", "/api/people/search"),
        ("POST", "/api/messages/draft"),
        ("POST", "/api/email/send"),
        ("GET", "/api/email/gmail/auth-url"),
        ("POST", "/api/linkedin-graph/import-batch"),
        ("POST", "/api/profile/resume"),
        ("POST", "/api/account/delete"),
        ("GET", "/api/companies/logo"),
        ("POST", "/api/waitlist"),
        ("PUT", "/api/settings/auto-prospect"),
        ("POST", "/api/settings/job-alerts/test"),
    ],
)
def test_demo_policy_blocks_external_or_destructive_actions(method, path):
    assert blocked_demo_action(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/jobs"),
        ("GET", "/api/people"),
        ("PUT", f"/api/jobs/{uuid.uuid4()}/stage"),
        ("PUT", "/api/profile"),
        ("PATCH", f"/api/stories/{uuid.uuid4()}"),
        ("GET", "/api/account/export"),
    ],
)
def test_demo_policy_allows_local_read_and_crm_workflows(method, path):
    assert blocked_demo_action(method, path) is None


@pytest.mark.asyncio
async def test_demo_middleware_returns_stable_error(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    response = await client.post("/api/jobs/discover", json={})
    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "DEMO_ACTION_DISABLED",
            "message": "Demo mode disables job discovery and generated job artifacts.",
            "details": None,
        }
    }
    assert response.headers["cache-control"] == "no-store"


def test_demo_fixture_ids_and_counts_are_deterministic():
    class FakeSession:
        def __init__(self):
            self.records = []

        def add(self, record):
            self.records.append(record)

        def add_all(self, records):
            self.records.extend(records)

    first = demo_uuid("job/product-engineer")
    assert first == demo_uuid("job/product-engineer")
    session = FakeSession()
    assert seed_returning_fixture(session) == {
        "companies": 3,
        "jobs": 5,
        "people": 6,
        "messages": 2,
        "outreach": 2,
    }
    assert len(session.records) == 19
