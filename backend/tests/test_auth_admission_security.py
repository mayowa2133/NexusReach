"""SEC-02: key misses and outages cannot amplify unauthenticated work."""

import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric import ec
import jwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app import auth_tokens
from app.config import settings


def _jwk(kid):
    key = ec.generate_private_key(ec.SECP256R1())
    value = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    return dict(value, kid=kid, use="sig", alg="ES256")


def test_repeated_concurrent_key_misses_do_not_refetch(monkeypatch):
    client = auth_tokens._JWKClient("https://unused.invalid", cache_jwk_set=True)
    key = _jwk("valid")
    calls = []

    def fetch(_self):
        calls.append(1)
        _self._last_successful_fetch = time.monotonic()
        return {"keys": [dict(key)]}

    with patch.object(jwt.PyJWKClient, "fetch_data", fetch):
        assert client.get_signing_key("valid").key_id == "valid"

        def miss(_):
            with pytest.raises(jwt.PyJWKClientError):
                client.get_signing_key("unknown")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(miss, range(30)))
        assert len(calls) == 1
        # Legitimate rotation resumes when the cooldown expires.
        client._last_successful_fetch -= 31
        key.update(kid="rotated")
        assert client.get_signing_key("rotated").key_id == "rotated"
        assert len(calls) == 2


def test_key_service_outage_is_backed_off():
    client = auth_tokens._JWKClient("https://unused.invalid")
    with patch.object(jwt.PyJWKClient, "fetch_data", side_effect=jwt.PyJWKClientConnectionError("down")) as fetch:
        for _ in range(10):
            with pytest.raises(jwt.PyJWKClientConnectionError):
                client.get_signing_key("unknown")
        assert fetch.call_count == 1


@pytest.mark.asyncio
async def test_admission_rejects_before_token_decoder(unauthed_client):
    with patch("app.middleware.auth_admission.consume", new=AsyncMock(side_effect=HTTPException(429, "limit"))), \
         patch.object(auth_tokens, "decode_supabase_token") as decode:
        response = await unauthed_client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 429
    decode.assert_not_called()


@pytest.mark.asyncio
async def test_oversize_token_rejected_before_key_lookup(unauthed_client):
    with patch.object(auth_tokens, "decode_supabase_token") as decode:
        response = await unauthed_client.get("/api/auth/me", headers={"Authorization": "Bearer " + "x" * settings.max_bearer_header_bytes})
    assert response.status_code == 431
    decode.assert_not_called()


def test_invalid_key_identifier_is_rejected_before_jwks(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://unused.invalid")
    header = base64.urlsafe_b64encode(json.dumps({"alg": "ES256", "kid": []}).encode()).rstrip(b"=").decode()
    with patch.object(auth_tokens, "_get_jwks_client") as client:
        with pytest.raises(jwt.InvalidTokenError):
            auth_tokens.decode_supabase_token(header + ".e30.AA")
        client.assert_not_called()


@pytest.mark.asyncio
async def test_prelaunch_app_also_applies_preauth_admission():
    from app.waitlist_app import app

    with patch("app.middleware.auth_admission.consume", new=AsyncMock(side_effect=HTTPException(429, "limit"))):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/referrals/status?code=ABC", headers={"Authorization": "Bearer nrw_synthetic"})
    assert response.status_code == 429
