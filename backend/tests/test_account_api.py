"""Account export and durable erasure API contracts."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.database import get_db
from app.main import app
from app.services.account_service import AccountDeletionUnavailableError
from app.services import deletion_service

pytestmark = pytest.mark.asyncio


@pytest.fixture
def dummy_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = None

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    yield db
    app.dependency_overrides.pop(get_db, None)


async def test_export_account_data_returns_private_download(client, dummy_db, mock_user_id):
    payload = {
        "exported_at": "2026-05-24T00:00:00+00:00",
        "user_id": str(mock_user_id),
        "format_version": 1,
        "redacted_fields": ["api_keys"],
        "tables": {"users": []},
    }
    with patch(
        "app.routers.account.account_service.export_user_data",
        new_callable=AsyncMock,
        return_value=payload,
    ):
        response = await client.get("/api/account/export")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]


async def test_delete_account_creates_tombstone_and_durable_receipt(
    client, dummy_db, mock_user_id
):
    request_id = uuid.uuid4()
    row = SimpleNamespace(id=request_id, status="pending")
    with (
        patch("app.routers.account.account_service.ensure_auth_deletion_available"),
        patch("app.services.identity_lifecycle.lock_subject", new_callable=AsyncMock),
        patch(
            "app.services.deletion_service.begin_request",
            new_callable=AsyncMock,
            return_value=(row, "nrd_receipt"),
        ) as begin,
        patch(
            "app.routers.account.account_service.delete_user_data",
            new_callable=AsyncMock,
            return_value={"users": 1},
        ) as delete_local,
        patch(
            "app.routers.account.account_service.delete_supabase_auth_user",
            new_callable=AsyncMock,
        ) as delete_upstream,
    ):
        response = await client.post(
            "/api/account/delete",
            json={"confirm": True},
            headers={"Idempotency-Key": "a" * 32},
        )

    assert response.status_code == 202
    assert response.json() == {
        "status": "pending",
        "request_id": str(request_id),
        "receipt_token": "nrd_receipt",
    }
    delete_local.assert_awaited_once_with(dummy_db, mock_user_id)
    delete_upstream.assert_not_awaited()
    assert dummy_db.add.call_count == 1
    assert dummy_db.add.call_args.args[0].subject == mock_user_id
    assert begin.await_args.args[3] == [("auth", str(mock_user_id))]


async def test_delete_account_preflight_failure_preserves_local_data(client, dummy_db):
    with (
        patch(
            "app.routers.account.account_service.ensure_auth_deletion_available",
            side_effect=AccountDeletionUnavailableError("service role missing"),
        ),
        patch(
            "app.routers.account.account_service.delete_user_data",
            new_callable=AsyncMock,
        ) as delete_local,
    ):
        response = await client.post("/api/account/delete", json={"confirm": True})
    assert response.status_code == 503
    delete_local.assert_not_awaited()


async def test_delete_account_requires_confirm(client, dummy_db):
    response = await client.post("/api/account/delete", json={"confirm": False})
    assert response.status_code == 400


async def test_export_account_data_requires_auth(unauthed_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    response = await unauthed_client.get("/api/account/export")
    assert response.status_code in (401, 403)


async def test_tombstone_retention_exceeds_access_token_lifetime(monkeypatch):
    monkeypatch.setattr(settings, "supabase_access_token_max_lifetime_seconds", 45 * 86400)
    assert deletion_service.tombstone_retention().days == 46


async def test_tombstone_retention_has_thirty_day_floor(monkeypatch):
    monkeypatch.setattr(settings, "supabase_access_token_max_lifetime_seconds", 3600)
    assert deletion_service.tombstone_retention().days == 30


async def test_deletion_receipt_is_stable_but_not_the_client_idempotency_key(
    monkeypatch,
):
    monkeypatch.setattr(settings, "deletion_receipt_hmac_key", "k" * 32)
    request_key = "client-visible-idempotency-key-12345"
    first = deletion_service._receipt("account:subject", request_key)
    second = deletion_service._receipt("account:subject", request_key)

    assert first == second
    assert first.startswith("nrd_")
    assert request_key not in first
    assert deletion_service._receipt("account:other", request_key) != first
