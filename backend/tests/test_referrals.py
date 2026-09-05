"""Security contracts for public referral and waitlist flows."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.models.waitlist import WaitlistSignup
from app.services import referral_service as rs
from app.services.waitlist_service import WaitlistUpsertResult


def _signup(**values) -> WaitlistSignup:
    defaults = {
        "id": uuid.uuid4(),
        "email": "owner@example.com",
        "name": "Owner",
        "referral_code": "ABCDEFGHJK",
        "referred_by_id": None,
        "email_verified": False,
        "verified_referral_count": 0,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(values)
    return WaitlistSignup(**defaults)


def _status_payload() -> dict:
    return {
        "referral_code": "ABCDEFGHJK",
        "position": 1,
        "total_verified": 1,
        "launch_target": 100,
        "share_url": "https://app.example/?ref=ABCDEFGHJK",
        "email_verified": True,
        "verified_referral_count": 0,
        "earned_tier": 0,
        "tier_thresholds": [1, 3, 5, 10],
    }


def test_owner_and_exchange_credentials_are_distinct_and_hashed():
    owner = rs.mint_access_token()
    exchange = rs.mint_verification_token()
    assert owner.startswith("nrw_")
    assert exchange.startswith("nrv_")
    assert not rs.hash_token(owner).startswith("nrw_")
    assert owner not in rs.hash_token(owner)


def test_email_links_put_credentials_in_fragments():
    dashboard = rs.build_dashboard_url("ABC", "nrw_token")
    verify = rs.build_verify_url("ABC", "nrv_token")
    assert dashboard.endswith("/r/ABC#t=nrw_token")
    assert verify.endswith("/r/ABC#v=nrv_token")
    assert "?t=" not in dashboard and "?v=" not in verify


def test_email_normalization_and_disposable_controls():
    assert rs.fraud_key("M.e+tag@Gmail.com") == "me@gmail.com"
    assert rs.fraud_key("a.b+tag@outlook.com") == "a.b@outlook.com"
    assert rs.is_disposable_email("x@mailinator.com") is True
    assert rs.is_disposable_email("x@example.com") is False


def test_reward_tiers_are_stable():
    assert rs.tier_thresholds() == [1, 3, 5, 10]
    assert [rs.earned_tier(value) for value in (0, 1, 4, 10)] == [0, 1, 3, 10]


@pytest.mark.asyncio
async def test_wrong_token_prefix_is_rejected_before_database_access():
    db = AsyncMock()
    assert await rs.resolve_signup_by_token(db, "ABC", "nrv_wrong_scope") is None
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("already", [False, True])
async def test_public_signup_response_is_generic_for_new_and_existing(client, already):
    signup = _signup()
    result = WaitlistUpsertResult(
        entry=signup,
        already_on_list=already,
        access_token=None,
        emailed_access_token=None,
        verification_token=None if already else "nrv_mailbox_only",
    )
    with (
        patch(
            "app.routers.waitlist.referral_service.enforce_signup_ip_limit",
            new_callable=AsyncMock,
        ),
        patch(
            "app.routers.waitlist.upsert_waitlist_signup",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch(
            "app.routers.waitlist.waitlist_resume_service.decode_and_validate",
            return_value=None,
        ),
        patch("app.routers.waitlist.send_verification_email.delay") as send_mail,
        patch("app.routers.waitlist.sheets_mirror_client.is_configured", return_value=False),
    ):
        response = await client.post(
            "/api/waitlist", json={"name": "Owner", "email": "owner@example.com"}
        )

    assert response.status_code == 202
    assert response.json() == {"ok": True}
    assert "token" not in response.text and "already" not in response.text
    assert send_mail.called is (not already)


@pytest.mark.asyncio
async def test_anonymous_resubmission_cannot_mutate_existing_row():
    from app.schemas.waitlist import WaitlistSignupCreate
    from app.services.waitlist_service import upsert_waitlist_signup

    existing = _signup(name="Real owner")
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db = AsyncMock()
    db.execute.return_value = result
    payload = WaitlistSignupCreate(
        name="Attacker", email=existing.email, note="replacement"
    )

    outcome = await upsert_waitlist_signup(db, payload)

    assert outcome.already_on_list is True
    assert outcome.verification_token is None
    assert existing.name == "Real owner" and existing.note is None
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_requires_owner_bearer(client):
    response = await client.get("/api/referrals/status?code=ABCDEFGHJK")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_status_accepts_scoped_owner_bearer(client):
    signup = _signup(email_verified=True)
    with (
        patch(
            "app.routers.referrals.referral_service.resolve_signup_by_token",
            new_callable=AsyncMock,
            return_value=signup,
        ) as resolve,
        patch(
            "app.routers.referrals.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=_status_payload(),
        ),
    ):
        response = await client.get(
            "/api/referrals/status?code=ABCDEFGHJK",
            headers={"Authorization": "Bearer nrw_owner"},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Owner"
    assert resolve.await_args.args[2] == "nrw_owner"


@pytest.mark.asyncio
async def test_exchange_consumes_post_body_and_returns_owner_token(client):
    signup = _signup(email_verified=True)
    with (
        patch(
            "app.routers.referrals.referral_service.verify_signup",
            new_callable=AsyncMock,
            return_value=(signup, "nrw_owner", None),
        ) as verify,
        patch(
            "app.routers.referrals.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=_status_payload(),
        ),
    ):
        response = await client.post(
            "/api/referrals/exchange",
            json={"code": "ABCDEFGHJK", "token": "nrv_mailbox"},
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "nrw_owner"
    verify.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_always_returns_generic_accepted(client):
    with patch(
        "app.services.referral_credentials.recovery_allowed",
        new_callable=AsyncMock,
        return_value=False,
    ):
        response = await client.post(
            "/api/referrals/recover", json={"email": "unknown@example.com"}
        )
    assert response.status_code == 202
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_public_signup_rejects_disposable_mailbox(client):
    response = await client.post(
        "/api/waitlist", json={"name": "Bot", "email": "bot@mailinator.com"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_waitlist_admin_export_is_hidden_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "waitlist_admin_token", "")
    response = await client.get("/api/waitlist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_waitlist_admin_export_rejects_bad_token(client, monkeypatch):
    monkeypatch.setattr(settings, "waitlist_admin_token", "x" * 64)
    response = await client.get(
        "/api/waitlist", headers={"X-Admin-Token": "wrong"}
    )
    assert response.status_code == 403
