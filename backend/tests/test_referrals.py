"""Referral service + router tests.

Follows the repo convention (conftest mocks the DB layer): pure helpers are
tested directly, DB-touching helpers against an ``AsyncMock`` session, and the
endpoints against the ``client`` fixture with the service patched.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.models.waitlist import WaitlistSignup
from app.services import referral_service as rs


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _db_returning(row, *more) -> AsyncMock:
    """AsyncMock db whose successive execute() calls return the given rows."""
    db = _mock_db()
    results = []
    for r in (row, *more):
        result = MagicMock()
        result.scalar_one_or_none.return_value = r
        results.append(result)
    db.execute.side_effect = results
    return db


def _count_db(*counts: int) -> AsyncMock:
    db = _mock_db()
    results = []
    for c in counts:
        result = MagicMock()
        result.scalar_one.return_value = c
        results.append(result)
    db.execute.side_effect = results
    return db


def _signup(**kw) -> WaitlistSignup:
    defaults = dict(
        id=uuid.uuid4(),
        email="user@example.com",
        name="Jordan Rivera",
        referral_code="ABCDEFGHJK",
        referred_by_id=None,
        email_verified=False,
        verified_at=None,
        verified_referral_count=0,
        access_token_hash=None,
        created_at=_now(),
    )
    defaults.update(kw)
    return WaitlistSignup(**defaults)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_hash_token_is_deterministic_and_token_has_prefix():
    token = rs.mint_access_token()
    assert token.startswith(rs.ACCESS_TOKEN_PREFIX)
    assert rs.hash_token(token) == rs.hash_token(token)
    assert token not in rs.hash_token(token)


def test_is_disposable_email():
    assert rs.is_disposable_email("throwaway@mailinator.com") is True
    assert rs.is_disposable_email("me@GUERRILLAMAIL.com") is True
    assert rs.is_disposable_email("real@gmail.com") is False
    assert rs.is_disposable_email("hire@stripe.com") is False


def test_fraud_key_normalizes_gmail_dots_and_plus_tags():
    assert rs.fraud_key("M.e+promo@Gmail.com") == "me@gmail.com"
    assert rs.fraud_key("me@gmail.com") == "me@gmail.com"
    # Plus-tag stripped for any provider, but dots preserved off-Gmail.
    assert rs.fraud_key("a.b+x@outlook.com") == "a.b@outlook.com"


def test_tier_thresholds_and_earned_tier():
    assert rs.tier_thresholds() == [1, 3, 5, 10]
    assert rs.earned_tier(0) == 0
    assert rs.earned_tier(1) == 1
    assert rs.earned_tier(2) == 1
    assert rs.earned_tier(3) == 3
    assert rs.earned_tier(4) == 3
    assert rs.earned_tier(5) == 5
    assert rs.earned_tier(11) == 10


def test_link_builders():
    assert rs.build_share_url("ABC").endswith("/?ref=ABC")
    assert "/r/ABC?t=nrw_tok" in rs.build_dashboard_url("ABC", "nrw_tok")
    verify = rs.build_verify_url("ABC", "nrw_tok")
    assert verify.endswith("/r/ABC?t=nrw_tok&verify=1")


# ---------------------------------------------------------------------------
# DB-backed helpers (mocked session)
# ---------------------------------------------------------------------------


async def test_mint_unique_referral_code_retries_on_collision():
    # First candidate collides (returns an id), second is free (None).
    db = _db_returning(uuid.uuid4(), None)
    code = await rs.mint_unique_referral_code(db)
    assert len(code) == rs._CODE_LEN
    assert all(ch in rs._CODE_ALPHABET for ch in code)
    assert db.execute.await_count == 2


async def test_resolve_referrer_blank_code_skips_db():
    db = _mock_db()
    assert await rs.resolve_referrer(db, None, "me@example.com") is None
    db.execute.assert_not_awaited()


async def test_resolve_referrer_returns_valid_referrer():
    referrer = _signup(email="ref@example.com", referral_code="REFCODE")
    db = _db_returning(referrer)
    resolved = await rs.resolve_referrer(db, "REFCODE", "invitee@example.com")
    assert resolved is referrer


async def test_resolve_referrer_rejects_self_referral():
    referrer = _signup(email="me@gmail.com", referral_code="MINE")
    db = _db_returning(referrer)
    # Same person (dot/plus variant) trying to use their own code.
    assert await rs.resolve_referrer(db, "MINE", "m.e+x@gmail.com") is None


async def test_resolve_signup_by_token_rejects_wrong_prefix_without_db():
    db = _mock_db()
    assert await rs.resolve_signup_by_token(db, "ABC", "eyJ...") is None
    db.execute.assert_not_awaited()


async def test_verify_signup_flips_and_credits_referrer():
    token = rs.mint_access_token()
    referrer_id = uuid.uuid4()
    signup = _signup(
        referred_by_id=referrer_id,
        access_token_hash=rs.hash_token(token),
    )
    # execute #1 = resolve_signup_by_token, #2 = referrer increment UPDATE.
    db = _db_returning(signup, None)

    out = await rs.verify_signup(db, signup.referral_code, token)

    assert out is signup
    assert signup.email_verified is True
    assert signup.verified_at is not None
    assert db.execute.await_count == 2  # resolve + increment
    db.commit.assert_awaited()


async def test_verify_signup_is_idempotent():
    token = rs.mint_access_token()
    signup = _signup(
        referred_by_id=uuid.uuid4(),
        email_verified=True,
        access_token_hash=rs.hash_token(token),
    )
    db = _db_returning(signup)  # only the resolve query

    out = await rs.verify_signup(db, signup.referral_code, token)

    assert out is signup
    assert db.execute.await_count == 1  # no second increment query
    db.commit.assert_not_awaited()


async def test_verify_signup_unknown_token_returns_none():
    db = _db_returning(None)
    token = rs.mint_access_token()
    assert await rs.verify_signup(db, "NOPE", token) is None
    db.commit.assert_not_awaited()


async def test_compute_position_is_one_plus_rows_ahead():
    signup = _signup(verified_referral_count=2)
    db = _count_db(41)
    assert await rs.compute_position(db, signup) == 42


async def test_referral_status_payload_composition():
    signup = _signup(referral_code="XYZ", verified_referral_count=3, email_verified=True)
    # execute #1 = compute_position (5 ahead => 6), #2 = count_verified (10).
    db = _count_db(5, 10)

    payload = await rs.referral_status_payload(db, signup)

    assert payload["referral_code"] == "XYZ"
    assert payload["position"] == 6
    assert payload["total_verified"] == 10
    assert payload["earned_tier"] == 3
    assert payload["tier_thresholds"] == [1, 3, 5, 10]
    assert payload["share_url"].endswith("/?ref=XYZ")
    assert payload["verified_referral_count"] == 3


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


_STATUS_PAYLOAD = {
    "referral_code": "ABCDEFGHJK",
    "position": 42,
    "total_verified": 10,
    "launch_target": 3000,
    "share_url": "http://localhost:5173/?ref=ABCDEFGHJK",
    "email_verified": False,
    "verified_referral_count": 0,
    "earned_tier": 0,
    "tier_thresholds": [1, 3, 5, 10],
}


async def test_join_waitlist_returns_referral_payload(client):
    entry = _signup(name="Jordan Rivera", email_verified=False)
    with (
        patch(
            "app.routers.waitlist.upsert_waitlist_signup",
            new_callable=AsyncMock,
            return_value=(entry, False, "nrw_secret"),
        ),
        patch(
            "app.routers.waitlist.referral_service.enforce_signup_ip_limit",
            new_callable=AsyncMock,
        ),
        patch(
            "app.routers.waitlist.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=dict(_STATUS_PAYLOAD),
        ),
        patch("app.routers.waitlist.send_verification_email.delay") as mock_delay,
    ):
        resp = await client.post(
            "/api/waitlist",
            json={"name": "Jordan Rivera", "email": "jordan@example.com"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "nrw_secret"
    assert body["referral_code"] == "ABCDEFGHJK"
    assert body["position"] == 42
    assert body["already_on_list"] is False
    # Unverified signup => verification email queued.
    mock_delay.assert_called_once()


async def test_join_waitlist_rejects_disposable_email(client):
    resp = await client.post(
        "/api/waitlist",
        json={"name": "Spammer", "email": "throwaway@mailinator.com"},
    )
    assert resp.status_code == 422


async def test_referral_status_endpoint(client):
    signup = _signup(name="Jordan")
    with (
        patch(
            "app.routers.referrals.referral_service.resolve_signup_by_token",
            new_callable=AsyncMock,
            return_value=signup,
        ),
        patch(
            "app.routers.referrals.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=dict(_STATUS_PAYLOAD),
        ),
    ):
        resp = await client.get("/api/referrals/status?code=ABCDEFGHJK&t=nrw_x")

    assert resp.status_code == 200
    assert resp.json()["position"] == 42


async def test_referral_status_unknown_token_404(client):
    with patch(
        "app.routers.referrals.referral_service.resolve_signup_by_token",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.get("/api/referrals/status?code=NOPE&t=nrw_x")
    assert resp.status_code == 404


async def test_verify_endpoint_credits_and_returns_status(client):
    signup = _signup(name="Jordan", email_verified=True, verified_referral_count=1)
    verified_payload = dict(_STATUS_PAYLOAD, email_verified=True)
    with (
        patch(
            "app.routers.referrals.referral_service.verify_signup",
            new_callable=AsyncMock,
            return_value=signup,
        ),
        patch(
            "app.routers.referrals.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=verified_payload,
        ),
    ):
        resp = await client.get("/api/referrals/verify?code=ABCDEFGHJK&t=nrw_x")

    assert resp.status_code == 200
    assert resp.json()["email_verified"] is True


async def test_verify_endpoint_bad_token_404(client):
    with patch(
        "app.routers.referrals.referral_service.verify_signup",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.get("/api/referrals/verify?code=NOPE&t=nrw_x")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Google Sheet mirror
# ---------------------------------------------------------------------------


async def test_sheet_mirror_noop_when_unconfigured(monkeypatch):
    from app.clients import sheets_mirror_client

    monkeypatch.setattr(settings, "waitlist_sheet_mirror_url", "")
    assert sheets_mirror_client.is_configured() is False
    # No network call, just a fast False.
    assert await sheets_mirror_client.mirror_signup({"email": "x@y.com"}) is False


async def test_join_waitlist_mirrors_to_sheet_when_configured(client):
    entry = _signup(name="Jordan Rivera", email_verified=False)
    with (
        patch(
            "app.routers.waitlist.upsert_waitlist_signup",
            new_callable=AsyncMock,
            return_value=(entry, False, "nrw_secret"),
        ),
        patch(
            "app.routers.waitlist.referral_service.enforce_signup_ip_limit",
            new_callable=AsyncMock,
        ),
        patch(
            "app.routers.waitlist.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=dict(_STATUS_PAYLOAD),
        ),
        patch("app.routers.waitlist.send_verification_email.delay"),
        patch(
            "app.routers.waitlist.sheets_mirror_client.is_configured",
            return_value=True,
        ),
        patch(
            "app.routers.waitlist.sheets_mirror_client.mirror_signup",
            new_callable=AsyncMock,
        ) as mock_mirror,
    ):
        resp = await client.post(
            "/api/waitlist",
            json={"name": "Jordan Rivera", "email": "jordan@example.com"},
        )

    assert resp.status_code == 200
    # Background task ran (Starlette awaits it within the ASGI response cycle).
    mock_mirror.assert_awaited_once()
    assert mock_mirror.await_args.args[0]["email"] == entry.email
    assert mock_mirror.await_args.args[0]["referral_code"] == entry.referral_code
