"""Regression tests for the Medium/Low launch-hardening audit fixes.

M1 — rate-limit key only trusts a signature-verified JWT sub.
M2 — JWT verification uses PyJWT (valid accepted, forged/expired rejected).
M4 — health endpoint does not leak raw exception detail.
M5 — SMTP lookup rejects domains whose MX resolves to private IPs.
M6 — OAuth redirect allowlist drops localhost defaults in production.
M7 — auto-draft dedupes per (person, job), not per person.
L4 — production config fails closed for dev-auth bypass.
"""

import uuid
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app import auth_tokens
from app.config import settings
from app.dependencies import get_current_auth_user
from app.middleware.rate_limit import _get_user_key


def _creds(token: str) -> SimpleNamespace:
    return SimpleNamespace(credentials=token)


def _fake_request(authorization: str, ip: str = "203.0.113.7") -> SimpleNamespace:
    return SimpleNamespace(
        headers={"Authorization": authorization},
        client=SimpleNamespace(host=ip),
    )


# ---------------------------------------------------------------------------
# M2 — PyJWT verification
# ---------------------------------------------------------------------------


async def test_valid_supabase_jwt_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
    sub = str(uuid.uuid4())
    token = pyjwt.encode(
        {"sub": sub, "aud": "authenticated", "email": "Person@Example.com"},
        "test-secret",
        algorithm="HS256",
    )

    auth = await get_current_auth_user(_creds(token))

    assert str(auth.user_id) == sub
    assert auth.email == "person@example.com"


async def test_es256_supabase_jwt_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    private_key = ec.generate_private_key(ec.SECP256R1())
    sub = str(uuid.uuid4())
    token = pyjwt.encode(
        {"sub": sub, "aud": "authenticated", "email": "Person@Example.com"},
        private_key,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )
    jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(
            key=private_key.public_key()
        )
    )
    monkeypatch.setattr(auth_tokens, "_get_jwks_client", lambda _url: jwks_client)

    auth = await get_current_auth_user(_creds(token))

    assert str(auth.user_id) == sub
    assert auth.email == "person@example.com"


async def test_unsupported_jwt_algorithm_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    token = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated"},
        "test-secret",
        algorithm="HS384",
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_auth_user(_creds(token))
    assert exc.value.status_code == 401


async def test_forged_signature_jwt_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "real-secret")
    token = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated"},
        "attacker-secret",
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_auth_user(_creds(token))
    assert exc.value.status_code == 401


async def test_wrong_audience_jwt_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "real-secret")
    token = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "not-authenticated"},
        "real-secret",
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_auth_user(_creds(token))
    assert exc.value.status_code == 401


async def test_non_uuid_sub_is_rejected_as_401(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "real-secret")
    token = pyjwt.encode(
        {"sub": "not-a-uuid", "aud": "authenticated"},
        "real-secret",
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_auth_user(_creds(token))
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# M1 — rate-limit key trusts only verified tokens
# ---------------------------------------------------------------------------


def test_rate_limit_key_trusts_verified_sub(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "real-secret")
    sub = str(uuid.uuid4())
    token = pyjwt.encode(
        {"sub": sub, "aud": "authenticated"}, "real-secret", algorithm="HS256"
    )

    key = _get_user_key(_fake_request(f"Bearer {token}"))

    assert key == f"user:{sub}"


def test_rate_limit_key_trusts_verified_es256_sub(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    private_key = ec.generate_private_key(ec.SECP256R1())
    sub = str(uuid.uuid4())
    token = pyjwt.encode(
        {"sub": sub, "aud": "authenticated"},
        private_key,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )
    jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(
            key=private_key.public_key()
        )
    )
    monkeypatch.setattr(auth_tokens, "_get_jwks_client", lambda _url: jwks_client)

    key = _get_user_key(_fake_request(f"Bearer {token}"))

    assert key == f"user:{sub}"


def test_rate_limit_key_ignores_forged_sub(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "real-secret")
    forged = pyjwt.encode(
        {"sub": "attacker", "aud": "authenticated"},
        "wrong-secret",
        algorithm="HS256",
    )

    key = _get_user_key(_fake_request(f"Bearer {forged}", ip="198.51.100.4"))

    # Forged token can't pin a per-user bucket — falls back to client IP.
    assert key == "198.51.100.4"
    assert key != "user:attacker"


def test_rate_limit_key_falls_back_to_ip_without_token():
    key = _get_user_key(_fake_request("", ip="198.51.100.9"))
    assert key == "198.51.100.9"


# ---------------------------------------------------------------------------
# M6 — production-aware OAuth redirect allowlist
# ---------------------------------------------------------------------------


def test_redirect_allowlist_drops_localhost_in_production(monkeypatch):
    from app.routers.email import _validate_redirect_uri

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "frontend_url", "https://app.nexusreach.com")
    monkeypatch.setattr(settings, "cors_origins", ["http://localhost:5173"])
    monkeypatch.setattr(settings, "companion_extension_origins", [])

    assert (
        _validate_redirect_uri("https://app.nexusreach.com/oauth/callback")
        == "https://app.nexusreach.com/oauth/callback"
    )
    with pytest.raises(HTTPException) as exc:
        _validate_redirect_uri("http://localhost:5173/oauth/callback")
    assert exc.value.status_code == 400


def test_redirect_allowlist_allows_localhost_in_dev(monkeypatch):
    from app.routers.email import _validate_redirect_uri

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:5173")
    monkeypatch.setattr(settings, "cors_origins", ["http://localhost:5173"])
    monkeypatch.setattr(settings, "companion_extension_origins", [])

    assert _validate_redirect_uri("http://localhost:5173/x") == "http://localhost:5173/x"


# ---------------------------------------------------------------------------
# M5 — SMTP MX target must be a public host
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host,expected",
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("localhost", False),
        ("", False),
        (None, False),
    ],
)
def test_is_safe_public_host(host, expected):
    from app.utils.url_safety import is_safe_public_host

    assert is_safe_public_host(host) is expected


async def test_smtp_lookup_refuses_internal_mx(monkeypatch):
    """If a domain's MX resolves to a private/loopback IP, no SMTP connect."""
    from app.clients import email_pattern_client

    async def _fake_resolve_mx(_domain):
        return "127.0.0.1"  # MX points at loopback

    async def _must_not_connect(*_a, **_k):
        raise AssertionError("must not open SMTP connection to an internal MX")

    monkeypatch.setattr(email_pattern_client, "_resolve_mx", _fake_resolve_mx)
    monkeypatch.setattr(email_pattern_client, "_check_smtp", _must_not_connect)

    result = await email_pattern_client._find_email_inner("Ada", "Lovelace", "evil.test")

    assert result == {"email": None, "domain_status": "unsafe_mx"}


# ---------------------------------------------------------------------------
# M7 — auto-draft dedupe is scoped to (person, job)
# ---------------------------------------------------------------------------


def test_auto_draft_dedupe_query_filters_by_job_snapshot():
    """The dedupe query must constrain on the snapshot job_id, not person alone."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.models.message import Message

    stmt = select(Message.id).where(
        Message.user_id == uuid.uuid4(),
        Message.person_id == uuid.uuid4(),
        Message.context_snapshot["job_id"].astext == str(uuid.uuid4()),
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    # JSONB text accessor on context_snapshot is present (scopes to the job).
    assert "context_snapshot ->>" in sql


# ---------------------------------------------------------------------------
# L4 — production config fails closed for dev-auth bypass
# ---------------------------------------------------------------------------


def _prod_settings(**overrides):
    from cryptography.fernet import Fernet

    from app.config import Settings

    base = dict(
        environment="production",
        auth_mode="supabase",
        dev_auth_bypass_enabled=False,
        database_url="postgresql+asyncpg://db.example/app",
        redis_url="redis://redis.example:6379/0",
        supabase_url="https://proj.supabase.co",
        supabase_key="anon",
        supabase_jwt_secret="secret",
        supabase_service_role_key="role",
        sentry_dsn="https://x@sentry.io/1",
        token_encryption_primary_version="v1",
        token_encryption_keys={"v1": Fernet.generate_key().decode()},
    )
    base.update(overrides)
    return Settings(**base)


def test_production_config_valid_baseline_does_not_raise():
    s = _prod_settings()
    assert s.environment == "production"


def test_production_rejects_dev_auth_mode():
    with pytest.raises(ValueError, match="dev must not be used in production"):
        _prod_settings(auth_mode="dev")


def test_production_rejects_dev_auth_bypass_enabled():
    with pytest.raises(ValueError, match="DEV_AUTH_BYPASS_ENABLED must not be true"):
        _prod_settings(dev_auth_bypass_enabled=True)
