"""Security regression coverage for OAuth state and PKCE transactions."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from app.services import gmail_service, oauth_transaction_service, outlook_service


@pytest.mark.asyncio
async def test_oauth_transaction_is_one_time_and_user_bound(monkeypatch):
    stored: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, *, ex, nx):
            assert ex == settings.oauth_transaction_ttl_seconds
            assert nx is True
            stored[key] = value
            return True

        async def get(self, key):
            return stored.get(key)

        async def getdel(self, key):
            return stored.pop(key, None)

    monkeypatch.setattr(oauth_transaction_service, "_redis_client", FakeRedis())
    user_id = uuid.uuid4()
    state, challenge = await oauth_transaction_service.create_transaction(
        user_id=user_id, provider="gmail", redirect_uri="https://app.example/settings"
    )

    assert state not in "".join(stored.values())
    assert challenge
    transaction = await oauth_transaction_service.consume_transaction(state=state, user_id=user_id)
    assert transaction.provider == "gmail"
    assert transaction.redirect_uri == "https://app.example/settings"
    assert transaction.code_verifier

    with pytest.raises(oauth_transaction_service.OAuthTransactionInvalidError):
        await oauth_transaction_service.consume_transaction(state=state, user_id=user_id)


@pytest.mark.asyncio
async def test_oauth_transaction_rejects_other_user_without_consuming_state(monkeypatch):
    stored: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, *, ex, nx):
            stored[key] = value
            return True

        async def get(self, key):
            return stored.get(key)

        async def getdel(self, key):
            return stored.pop(key, None)

    monkeypatch.setattr(oauth_transaction_service, "_redis_client", FakeRedis())
    owner = uuid.uuid4()
    state, _ = await oauth_transaction_service.create_transaction(
        user_id=owner, provider="outlook", redirect_uri="https://app.example/settings"
    )

    with pytest.raises(oauth_transaction_service.OAuthTransactionInvalidError):
        await oauth_transaction_service.consume_transaction(state=state, user_id=uuid.uuid4())
    transaction = await oauth_transaction_service.consume_transaction(state=state, user_id=owner)
    assert transaction.provider == "outlook"


@pytest.mark.parametrize("service", [gmail_service, outlook_service])
def test_provider_auth_url_enforces_pkce_and_state(service):
    url = service.get_auth_url(
        "https://app.example/settings", state="opaque-state", code_challenge="challenge"
    )
    query = parse_qs(urlparse(url).query)
    assert query["state"] == ["opaque-state"]
    assert query["code_challenge"] == ["challenge"]
    assert query["code_challenge_method"] == ["S256"]
