"""Companion token service, router, and dual-auth dependency tests."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.companion_token import CompanionToken
from app.services import companion_tokens

pytestmark = pytest.mark.asyncio

USER_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _row(
    *,
    expires_in: timedelta = timedelta(days=30),
    revoked: bool = False,
    last_used_at: datetime | None = None,
) -> CompanionToken:
    return CompanionToken(
        id=uuid.uuid4(),
        user_id=USER_ID,
        token_hash="x" * 64,
        expires_at=_now() + expires_in,
        last_used_at=last_used_at,
        revoked_at=_now() if revoked else None,
    )


def _db_returning(row: CompanionToken | None) -> AsyncMock:
    db = _mock_db()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


async def test_mint_token_stores_hash_only_and_revokes_previous():
    db = _mock_db()

    token, _row_out = await companion_tokens.mint_token(db, USER_ID)

    assert token.startswith(companion_tokens.COMPANION_TOKEN_PREFIX)
    added = db.add.call_args.args[0]
    assert added.token_hash == companion_tokens.hash_token(token)
    assert token not in added.token_hash
    # Revocation UPDATE for previously active tokens was issued.
    assert db.execute.await_count == 1
    # TTL matches the configured window (generous tolerance).
    delta = added.expires_at - _now()
    assert timedelta(days=179) < delta < timedelta(days=181)


async def test_resolve_token_rejects_wrong_prefix_without_db():
    db = _mock_db()
    assert await companion_tokens.resolve_token(db, "eyJhbGciOi...") is None
    db.execute.assert_not_awaited()


async def test_resolve_token_rejects_unknown_revoked_expired():
    assert await companion_tokens.resolve_token(_db_returning(None), "nrc_x") is None
    assert (
        await companion_tokens.resolve_token(_db_returning(_row(revoked=True)), "nrc_x")
        is None
    )
    expired = _row(expires_in=timedelta(seconds=-1))
    assert await companion_tokens.resolve_token(_db_returning(expired), "nrc_x") is None


async def test_resolve_token_accepts_valid_and_touches_last_used():
    row = _row(last_used_at=None)
    db = _db_returning(row)

    assert await companion_tokens.resolve_token(db, "nrc_x") == USER_ID
    assert row.last_used_at is not None
    db.commit.assert_awaited()


async def test_resolve_token_throttles_last_used_writes():
    row = _row(last_used_at=_now() - timedelta(minutes=5))
    db = _db_returning(row)

    assert await companion_tokens.resolve_token(db, "nrc_x") == USER_ID
    db.commit.assert_not_awaited()


async def test_revoke_tokens_returns_count():
    db = _mock_db()
    db.execute.return_value = MagicMock(rowcount=2)

    assert await companion_tokens.revoke_tokens(db, USER_ID) == 2
    db.commit.assert_awaited()


async def test_get_status_disconnected_and_connected():
    assert (await companion_tokens.get_status(_db_returning(None), USER_ID)) == {
        "connected": False,
        "created_at": None,
        "last_used_at": None,
        "expires_at": None,
    }

    row = _row()
    row.created_at = _now()
    status = await companion_tokens.get_status(_db_returning(row), USER_ID)
    assert status["connected"] is True
    assert status["expires_at"] == row.expires_at


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


async def test_mint_endpoint_returns_token_once(client):
    row = _row()
    with patch(
        "app.routers.companion.companion_tokens.mint_token",
        new_callable=AsyncMock,
    ) as mock_mint:
        mock_mint.return_value = ("nrc_plaintext", row)
        response = await client.post("/api/companion/token")

    assert response.status_code == 200
    body = response.json()
    assert body["token"] == "nrc_plaintext"
    assert body["expires_at"] is not None


async def test_revoke_endpoint_returns_count(client):
    with patch(
        "app.routers.companion.companion_tokens.revoke_tokens",
        new_callable=AsyncMock,
    ) as mock_revoke:
        mock_revoke.return_value = 1
        response = await client.delete("/api/companion/token")

    assert response.status_code == 200
    assert response.json()["revoked"] == 1


async def test_status_endpoint(client):
    with patch(
        "app.routers.companion.companion_tokens.get_status",
        new_callable=AsyncMock,
    ) as mock_status:
        mock_status.return_value = {
            "connected": False,
            "created_at": None,
            "last_used_at": None,
            "expires_at": None,
        }
        response = await client.get("/api/companion/status")

    assert response.status_code == 200
    assert response.json()["connected"] is False


async def test_mint_endpoint_requires_full_auth(unauthed_client):
    """A companion token must not be able to mint its own successor."""
    response = await unauthed_client.post(
        "/api/companion/token",
        headers={"Authorization": "Bearer nrc_stolen"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Dual-auth dependency on a companion-callable endpoint
# ---------------------------------------------------------------------------


async def test_companion_token_accepted_on_linkedin_graph_status(unauthed_client):
    with (
        patch(
            "app.dependencies.companion_tokens.resolve_token",
            new_callable=AsyncMock,
        ) as mock_resolve,
        patch(
            "app.routers.linkedin_graph.linkedin_graph_service.get_status",
            new_callable=AsyncMock,
        ) as mock_status,
    ):
        mock_resolve.return_value = USER_ID
        mock_status.return_value = {
            "connected": True,
            "source": "browser_sync",
            "last_synced_at": None,
            "sync_status": "completed",
            "last_error": None,
            "connection_count": 5,
            "last_run": None,
        }
        response = await unauthed_client.get(
            "/api/linkedin-graph/status",
            headers={"Authorization": "Bearer nrc_valid"},
        )

    assert response.status_code == 200
    assert mock_status.await_args.args[1] == USER_ID


async def test_invalid_companion_token_rejected(unauthed_client):
    with patch(
        "app.dependencies.companion_tokens.resolve_token",
        new_callable=AsyncMock,
    ) as mock_resolve:
        mock_resolve.return_value = None
        response = await unauthed_client.get(
            "/api/linkedin-graph/status",
            headers={"Authorization": "Bearer nrc_revoked"},
        )

    assert response.status_code == 401
