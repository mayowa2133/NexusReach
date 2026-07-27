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
        verification_token_hash=None,
        created_at=_now(),
    )
    defaults.update(kw)
    return WaitlistSignup(**defaults)


def _upsert_result(entry, **kw):
    """A ``WaitlistUpsertResult`` with new-signup defaults."""
    from app.services.waitlist_service import WaitlistUpsertResult

    fields = dict(
        entry=entry,
        already_on_list=False,
        access_token="nrw_secret",
        emailed_access_token=None,
        verification_token="nrv_secret",
    )
    fields.update(kw)
    return WaitlistUpsertResult(**fields)


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
    # The confirmation link carries the single-use token under a distinct
    # parameter, so the two secrets can't be confused at either end.
    assert rs.build_verify_url("ABC", "nrv_tok").endswith("/r/ABC?v=nrv_tok")


def test_verification_token_has_its_own_prefix():
    token = rs.mint_verification_token()
    assert token.startswith(rs.VERIFICATION_TOKEN_PREFIX)
    assert not token.startswith(rs.ACCESS_TOKEN_PREFIX)


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
    token = rs.mint_verification_token()
    referrer_id = uuid.uuid4()
    signup = _signup(
        referred_by_id=referrer_id,
        verification_token_hash=rs.hash_token(token),
    )
    # execute #1 = resolve by verification token, #2 = referrer increment UPDATE.
    db = _db_returning(signup, None)

    out = await rs.verify_signup(db, signup.referral_code, token)

    assert out is not None
    verified, access_token, credited_referrer_id = out
    assert verified is signup
    assert signup.email_verified is True
    assert signup.verified_at is not None
    # The confirmation key is single-use; a dashboard key is issued in exchange.
    assert signup.verification_token_hash is None
    assert access_token.startswith(rs.ACCESS_TOKEN_PREFIX)
    assert signup.access_token_hash == rs.hash_token(access_token)
    assert db.execute.await_count == 2  # resolve + increment
    db.commit.assert_awaited()
    # Reported so the caller can notify exactly the person who was credited.
    assert credited_referrer_id == referrer_id


async def test_verify_signup_reports_no_credit_for_an_organic_signup():
    """Nobody to notify when the member wasn't referred."""
    token = rs.mint_verification_token()
    signup = _signup(referred_by_id=None, verification_token_hash=rs.hash_token(token))
    db = _db_returning(signup)

    out = await rs.verify_signup(db, signup.referral_code, token)

    assert out is not None
    assert out[2] is None


async def test_verify_signup_reports_no_credit_on_re_confirmation():
    """An already-verified row must not re-credit — nor re-notify — its referrer."""
    token = rs.mint_verification_token()
    signup = _signup(
        referred_by_id=uuid.uuid4(),
        email_verified=True,
        verification_token_hash=rs.hash_token(token),
    )
    db = _db_returning(signup)

    out = await rs.verify_signup(db, signup.referral_code, token)

    assert out is not None
    assert out[2] is None
    assert db.execute.await_count == 1  # resolve only; no increment


async def test_verify_signup_rejects_the_dashboard_access_token():
    """The owner key must not double as a confirmation key.

    This is the whole point of the two-token split: the access token is handed
    to the browser on join, so accepting it here would let anyone confirm any
    address they typed into the form and farm referral credit.
    """
    access_token = rs.mint_access_token()
    signup = _signup(
        referred_by_id=uuid.uuid4(),
        access_token_hash=rs.hash_token(access_token),
    )
    db = _db_returning(signup, None)

    assert await rs.verify_signup(db, signup.referral_code, access_token) is None
    db.execute.assert_not_awaited()  # rejected on the prefix, before any query
    assert signup.email_verified is False
    db.commit.assert_not_awaited()


async def test_verify_signup_replayed_link_does_not_double_count():
    """A second click finds nothing: the token was consumed by the first."""
    db = _db_returning(None)  # token hash no longer matches any row
    token = rs.mint_verification_token()
    assert await rs.verify_signup(db, "ABCDEFGHJK", token) is None
    db.commit.assert_not_awaited()


async def test_verify_signup_unknown_token_returns_none():
    db = _db_returning(None)
    token = rs.mint_verification_token()
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
            return_value=_upsert_result(entry),
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
    assert body["referral"]["referral_code"] == "ABCDEFGHJK"
    assert body["referral"]["position"] == 42
    assert body["already_on_list"] is False
    # Unverified signup => verification email queued with the emailed-only token.
    mock_delay.assert_called_once()
    assert mock_delay.call_args.args[1] == "nrv_secret"


async def test_join_waitlist_existing_email_discloses_nothing(client):
    """Submitting an address already on the list must not leak or grant anything.

    The endpoint is unauthenticated, so this branch is reachable by anyone who
    guesses an email. Returning that row's owner token, name or queue position
    would be an account takeover plus an enumeration oracle.
    """
    entry = _signup(name="Jordan Rivera", email_verified=False)
    with (
        patch(
            "app.routers.waitlist.upsert_waitlist_signup",
            new_callable=AsyncMock,
            return_value=_upsert_result(
                entry, already_on_list=True, access_token=None
            ),
        ),
        patch(
            "app.routers.waitlist.referral_service.enforce_signup_ip_limit",
            new_callable=AsyncMock,
        ),
        patch("app.routers.waitlist.send_verification_email.delay"),
    ):
        resp = await client.post(
            "/api/waitlist",
            json={"name": "Attacker", "email": "jordan@example.com"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "already_on_list": True, "access_token": None, "referral": None}
    serialized = resp.text
    assert "Jordan Rivera" not in serialized
    assert "ABCDEFGHJK" not in serialized
    assert "nrw_" not in serialized and "nrv_" not in serialized


async def test_resubmission_does_not_mutate_the_existing_row():
    """An unauthenticated caller must not be able to rewrite someone's entry.

    Anyone can submit any address here, so a "helpful" merge of the submitted
    details is really a stranger editing the owner's name, LinkedIn URL and
    note — visible to them on their own dashboard.
    """
    from app.schemas.waitlist import WaitlistSignupCreate
    from app.services.waitlist_service import upsert_waitlist_signup

    existing = _signup(
        name="Real Owner",
        email="owner@example.com",
        linkedin_url="https://linkedin.com/in/real-owner",
        current_title="Staff Engineer",
        target_role="Engineering Manager",
        note="Original note",
        source="landing",
        goals=["warm_intros"],
    )
    db = _db_returning(existing)

    result = await upsert_waitlist_signup(
        db,
        WaitlistSignupCreate(
            name="Attacker Overwrite",
            email="owner@example.com",
            linkedin_url="https://evil.example/profile",
            current_title="Nonsense",
            target_role="Nonsense",
            note="Graffiti",
            source="attack",
            goals=["internships"],
        ),
    )

    assert result.already_on_list is True
    assert existing.name == "Real Owner"
    assert existing.linkedin_url == "https://linkedin.com/in/real-owner"
    assert existing.current_title == "Staff Engineer"
    assert existing.target_role == "Engineering Manager"
    assert existing.note == "Original note"
    assert existing.source == "landing"
    assert existing.goals == ["warm_intros"]


async def test_join_waitlist_verified_resubmission_emails_dashboard_link(client):
    """A returning verified member is re-authenticated through their mailbox."""
    entry = _signup(name="Jordan Rivera", email_verified=True)
    with (
        patch(
            "app.routers.waitlist.upsert_waitlist_signup",
            new_callable=AsyncMock,
            return_value=_upsert_result(
                entry,
                already_on_list=True,
                access_token=None,
                emailed_access_token="nrw_emailed",
                verification_token=None,
            ),
        ),
        patch(
            "app.routers.waitlist.referral_service.enforce_signup_ip_limit",
            new_callable=AsyncMock,
        ),
        patch("app.routers.waitlist.send_verification_email.delay") as mock_verify,
        patch("app.routers.waitlist.send_dashboard_link_email.delay") as mock_link,
    ):
        resp = await client.post(
            "/api/waitlist",
            json={"name": "Jordan Rivera", "email": "jordan@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["access_token"] is None
    mock_verify.assert_not_called()
    mock_link.assert_called_once()
    assert mock_link.call_args.args[1] == "nrw_emailed"


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
    referrer_id = uuid.uuid4()
    with (
        patch(
            "app.routers.referrals.referral_service.verify_signup",
            new_callable=AsyncMock,
            return_value=(signup, "nrw_fresh", referrer_id),
        ),
        patch(
            "app.routers.referrals.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=verified_payload,
        ),
        patch(
            "app.routers.referrals.send_referral_credited_email.delay"
        ) as mock_notify,
    ):
        resp = await client.get("/api/referrals/verify?code=ABCDEFGHJK&v=nrv_x")

    assert resp.status_code == 200
    body = resp.json()
    assert body["email_verified"] is True
    # Clicking the emailed link proves mailbox control, so the dashboard key is
    # issued here rather than at signup.
    assert body["access_token"] == "nrw_fresh"
    # The referrer is told they moved up — the nudge that drives the next share.
    mock_notify.assert_called_once_with(str(referrer_id))


async def test_verify_endpoint_does_not_notify_without_a_credit(client):
    """Organic signup or replayed link => nobody was credited, so no email."""
    signup = _signup(name="Jordan", email_verified=True)
    with (
        patch(
            "app.routers.referrals.referral_service.verify_signup",
            new_callable=AsyncMock,
            return_value=(signup, "nrw_fresh", None),
        ),
        patch(
            "app.routers.referrals.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=dict(_STATUS_PAYLOAD),
        ),
        patch(
            "app.routers.referrals.send_referral_credited_email.delay"
        ) as mock_notify,
    ):
        resp = await client.get("/api/referrals/verify?code=ABCDEFGHJK&v=nrv_x")

    assert resp.status_code == 200
    mock_notify.assert_not_called()


async def test_verify_endpoint_survives_a_broker_outage(client):
    """A dead queue must not cost the visitor their confirmation."""
    signup = _signup(name="Jordan", email_verified=True)
    with (
        patch(
            "app.routers.referrals.referral_service.verify_signup",
            new_callable=AsyncMock,
            return_value=(signup, "nrw_fresh", uuid.uuid4()),
        ),
        patch(
            "app.routers.referrals.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=dict(_STATUS_PAYLOAD),
        ),
        patch(
            "app.routers.referrals.send_referral_credited_email.delay",
            side_effect=RuntimeError("broker down"),
        ),
    ):
        resp = await client.get("/api/referrals/verify?code=ABCDEFGHJK&v=nrv_x")

    assert resp.status_code == 200


async def test_verify_endpoint_bad_token_404(client):
    with patch(
        "app.routers.referrals.referral_service.verify_signup",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.get("/api/referrals/verify?code=NOPE&v=nrv_x")
    assert resp.status_code == 404


async def test_verify_endpoint_requires_the_v_parameter(client):
    """The old ``?t=`` shape carried the access token — it must not verify."""
    resp = await client.get("/api/referrals/verify?code=ABCDEFGHJK&t=nrw_x")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------


def test_verification_email_escapes_the_submitted_name():
    """``name`` is untrusted free text from a public form.

    These messages go out over our own verified sending domain, so an unescaped
    value would let anyone mail arbitrary markup — an attacker-chosen link in a
    message recipients have every reason to trust — to any address they name.
    """
    from app.tasks.referrals import _render_verification_email

    html = _render_verification_email(
        '</p><a href="https://evil.example">Click here</a><p>',
        "https://solomon.test/r/ABCDEFGHJK?v=nrv_token",
    )

    assert "<a href=\"https://evil.example\">" not in html
    assert "&lt;/p&gt;&lt;a href=" in html
    # The one legitimate anchor is ours.
    assert html.count("https://evil.example") == 1  # inert, inside escaped text


def test_dashboard_link_email_escapes_the_submitted_name():
    from app.tasks.referrals import _render_dashboard_link_email

    html = _render_dashboard_link_email(
        "<img src=x onerror=alert(1)>",
        "https://solomon.test/r/ABCDEFGHJK?t=nrw_token",
    )

    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_email_greeting_handles_a_missing_name():
    from app.tasks.referrals import _greeting

    assert _greeting(None) == "Hi,"
    assert _greeting("   ") == "Hi,"
    assert _greeting("Jordan") == "Hi Jordan,"


def test_referral_credited_email_escapes_the_submitted_name():
    from app.tasks.referrals import _render_referral_credited_email

    html = _render_referral_credited_email(
        "<script>alert(1)</script>",
        42,
        3,
        "https://solomon.test/r/ABCDEFGHJK",
        None,
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_referral_credited_email_reports_position_and_count():
    from app.tasks.referrals import _render_referral_credited_email

    html = _render_referral_credited_email("Jordan", 1284, 1, "https://x.test/r/A", None)

    assert "#1,284" in html  # thousands-separated for readability
    assert "<strong>1</strong> confirmed referral" in html
    assert "referrals" not in html  # singular at a count of one


def test_referral_credited_email_calls_out_a_newly_unlocked_tier():
    from app.tasks.referrals import _render_referral_credited_email

    html = _render_referral_credited_email(
        "Jordan", 7, 3, "https://x.test/r/A", "a new reward at 3 referrals"
    )
    assert "a new reward at 3 referrals" in html


async def test_referral_credited_notice_never_mints_a_fresh_token():
    """The nudge must not rotate the referrer's dashboard key.

    ``issue_access_token`` overwrites ``access_token_hash``; doing that here
    would sign the referrer out of a dashboard they may have open, so the email
    links to the bare ``/r/{code}`` page instead.
    """
    from app.tasks import referrals as referral_tasks

    referrer = _signup(
        name="Ada", email_verified=True, verified_referral_count=2
    )
    referrer.access_token_hash = "original-hash"

    with (
        patch.object(
            referral_tasks, "_load_signup", new_callable=AsyncMock, return_value=referrer
        ),
        patch.object(
            referral_tasks, "compute_position", new_callable=AsyncMock, return_value=12
        ),
        patch.object(
            referral_tasks.resend_client,
            "send_email",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send,
    ):
        result = await referral_tasks._run_referral_credited(str(referrer.id))

    assert result["sent"] is True
    assert referrer.access_token_hash == "original-hash"  # untouched
    # No secret is carried in the link.
    body = mock_send.await_args.kwargs["html"]
    assert "?t=" not in body and "nrw_" not in body


async def test_referral_credited_notice_skips_an_unverified_referrer():
    """Unsolicited mail only goes to an address whose owner confirmed it."""
    from app.tasks import referrals as referral_tasks

    referrer = _signup(name="Ada", email_verified=False)

    with (
        patch.object(
            referral_tasks, "_load_signup", new_callable=AsyncMock, return_value=referrer
        ),
        patch.object(
            referral_tasks.resend_client, "send_email", new_callable=AsyncMock
        ) as mock_send,
    ):
        result = await referral_tasks._run_referral_credited(str(referrer.id))

    assert result == {"sent": False, "reason": "referrer_unverified"}
    mock_send.assert_not_awaited()


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
            return_value=_upsert_result(entry),
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


# ---------------------------------------------------------------------------
# Admin export hardening (finding #8)
# ---------------------------------------------------------------------------


async def test_admin_export_rejects_a_bad_token(client, monkeypatch):
    monkeypatch.setattr(settings, "waitlist_admin_token", "x" * 40)
    resp = await client.get("/api/waitlist", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


async def test_admin_export_is_404_when_unconfigured(client, monkeypatch):
    """Unset => the endpoint's existence isn't advertised at all."""
    monkeypatch.setattr(settings, "waitlist_admin_token", "")
    resp = await client.get("/api/waitlist", headers={"X-Admin-Token": "anything"})
    assert resp.status_code == 404


def test_production_rejects_a_short_admin_token():
    """A guessable secret guarding the whole signup list must not deploy."""
    import pytest

    from app.config import MIN_ADMIN_TOKEN_LENGTH

    with pytest.raises(ValueError, match="WAITLIST_ADMIN_TOKEN"):
        _prod_settings_for_admin_token("short")

    # At the boundary it is accepted.
    s = _prod_settings_for_admin_token("a" * MIN_ADMIN_TOKEN_LENGTH)
    assert len(s.waitlist_admin_token) == MIN_ADMIN_TOKEN_LENGTH


def _prod_settings_for_admin_token(token: str):
    from cryptography.fernet import Fernet

    from app.config import Settings

    return Settings(
        _env_file=None,
        environment="production",
        auth_mode="supabase",
        database_url="postgresql+asyncpg://db.example/app",
        redis_url="redis://redis.example:6379/0",
        supabase_url="https://proj.supabase.co",
        supabase_key="anon",
        supabase_jwt_secret="secret",
        supabase_service_role_key="role",
        sentry_dsn="https://x@sentry.io/1",
        token_encryption_primary_version="v1",
        token_encryption_keys={"v1": Fernet.generate_key().decode()},
        render_remote_enabled=True,
        trusted_proxy_hops=1,
        waitlist_admin_token=token,
    )
