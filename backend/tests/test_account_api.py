"""Tests for account export and deletion endpoints."""

from unittest.mock import AsyncMock, patch

import pytest

from app.database import get_db
from app.main import app
from app.config import settings
from app.services.account_service import AccountDeletionUnavailableError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def dummy_db():
    db = object()

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    yield db
    app.dependency_overrides.pop(get_db, None)


async def test_export_account_data_returns_download(client, dummy_db, mock_user_id):
    payload = {
        "exported_at": "2026-05-24T00:00:00+00:00",
        "user_id": str(mock_user_id),
        "format_version": 1,
        "redacted_fields": ["api_keys", "gmail_refresh_token", "outlook_refresh_token"],
        "tables": {"users": []},
    }

    with patch(
        "app.routers.account.account_service.export_user_data",
        new_callable=AsyncMock,
        return_value=payload,
    ) as export_user_data:
        resp = await client.get("/api/account/export")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.json() == payload
    export_user_data.assert_awaited_once_with(dummy_db, mock_user_id)


async def test_delete_account_deletes_app_data_before_auth_identity(
    client,
    dummy_db,
    mock_user_id,
):
    """App data must be deleted BEFORE the auth identity (audit H3)."""
    call_order: list[str] = []

    async def _record_data(*_args, **_kwargs):
        call_order.append("data")
        return {"users": 1, "profiles": 1}

    async def _record_auth(*_args, **_kwargs):
        call_order.append("auth")
        return True

    with (
        patch(
            "app.routers.account.account_service.ensure_auth_deletion_available",
        ),
        patch(
            "app.routers.account.account_service.delete_supabase_auth_user",
            new=AsyncMock(side_effect=_record_auth),
        ) as delete_auth,
        patch(
            "app.routers.account.account_service.delete_user_data",
            new=AsyncMock(side_effect=_record_data),
        ) as delete_data,
    ):
        resp = await client.post("/api/account/delete", json={"confirm": True})

    assert resp.status_code == 200
    assert resp.json() == {
        "deleted": True,
        "auth_identity_deleted": True,
        "deleted_tables": {"users": 1, "profiles": 1},
    }
    delete_auth.assert_awaited_once_with(mock_user_id)
    delete_data.assert_awaited_once_with(dummy_db, mock_user_id)
    assert call_order == ["data", "auth"]


async def test_delete_account_preflight_failure_does_not_delete_data(
    client,
    dummy_db,
):
    """If auth deletion is impossible up front, app data must NOT be deleted."""
    with (
        patch(
            "app.routers.account.account_service.ensure_auth_deletion_available",
            side_effect=AccountDeletionUnavailableError("service role missing"),
        ),
        patch(
            "app.routers.account.account_service.delete_user_data",
            new_callable=AsyncMock,
        ) as delete_data,
        patch(
            "app.routers.account.account_service.delete_supabase_auth_user",
            new_callable=AsyncMock,
        ) as delete_auth,
    ):
        resp = await client.post("/api/account/delete", json={"confirm": True})

    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "service role missing"
    delete_data.assert_not_awaited()
    delete_auth.assert_not_awaited()


async def test_delete_account_transient_auth_failure_after_data_deleted(
    client,
    dummy_db,
    mock_user_id,
):
    """A transient auth-delete failure must still leave app data deleted (H3).

    The privacy-critical removal happens first; the endpoint surfaces a
    retryable 503 rather than rolling the data back.
    """
    with (
        patch(
            "app.routers.account.account_service.ensure_auth_deletion_available",
        ),
        patch(
            "app.routers.account.account_service.delete_user_data",
            new_callable=AsyncMock,
            return_value={"users": 1},
        ) as delete_data,
        patch(
            "app.routers.account.account_service.delete_supabase_auth_user",
            new_callable=AsyncMock,
            side_effect=AccountDeletionUnavailableError("supabase 502"),
        ) as delete_auth,
    ):
        resp = await client.post("/api/account/delete", json={"confirm": True})

    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "supabase 502"
    # Data was deleted before the auth attempt failed — not rolled back.
    delete_data.assert_awaited_once_with(dummy_db, mock_user_id)
    delete_auth.assert_awaited_once_with(mock_user_id)


async def test_delete_account_requires_confirm(client, dummy_db):
    with (
        patch(
            "app.routers.account.account_service.delete_supabase_auth_user",
            new_callable=AsyncMock,
        ) as delete_auth,
        patch(
            "app.routers.account.account_service.delete_user_data",
            new_callable=AsyncMock,
        ) as delete_data,
    ):
        resp = await client.post("/api/account/delete", json={"confirm": False})

    assert resp.status_code == 400
    delete_auth.assert_not_awaited()
    delete_data.assert_not_awaited()


async def test_export_account_data_requires_auth(unauthed_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    resp = await unauthed_client.get("/api/account/export")
    assert resp.status_code in (401, 403)
