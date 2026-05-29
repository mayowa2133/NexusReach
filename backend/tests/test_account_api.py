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


async def test_delete_account_deletes_auth_identity_then_app_data(
    client,
    dummy_db,
    mock_user_id,
):
    with (
        patch(
            "app.routers.account.account_service.delete_supabase_auth_user",
            new_callable=AsyncMock,
            return_value=True,
        ) as delete_auth,
        patch(
            "app.routers.account.account_service.delete_user_data",
            new_callable=AsyncMock,
            return_value={"users": 1, "profiles": 1},
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


async def test_delete_account_reports_auth_deletion_unavailable(client, dummy_db):
    with (
        patch(
            "app.routers.account.account_service.delete_supabase_auth_user",
            new_callable=AsyncMock,
            side_effect=AccountDeletionUnavailableError("service role missing"),
        ),
        patch(
            "app.routers.account.account_service.delete_user_data",
            new_callable=AsyncMock,
        ) as delete_data,
    ):
        resp = await client.post("/api/account/delete", json={"confirm": True})

    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == "service role missing"
    delete_data.assert_not_awaited()


async def test_export_account_data_requires_auth(unauthed_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    resp = await unauthed_client.get("/api/account/export")
    assert resp.status_code in (401, 403)
