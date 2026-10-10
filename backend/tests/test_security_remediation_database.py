"""Opt-in regression races against the disposable audit PostgreSQL only."""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.job import Job
from app.models.profile import Profile
from app.models.profile_rescore import ProfileRescoreRequest
from app.models.referral_security import ReferralCampaign, ReferralCredit
from app.models.user import User
from app.models.waitlist import WaitlistSignup
from app.services import profile_rescore_service as outbox
from app.services import referral_credentials as credentials
from app.services import referral_service

pytestmark = pytest.mark.skipif(os.environ.get("NEXUS_SECURITY_DB_TESTS") != "1",
                                reason="requires disposable audit PostgreSQL")


@pytest_asyncio.fixture
async def database(monkeypatch):
    engine = create_async_engine("postgresql+asyncpg://audit:audit-local-only@127.0.0.1:55439/nexusreach_security_audit")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=uid, email=f"{uid}@example.test"))
        await db.flush()
        db.add(Profile(user_id=uid, full_name="Synthetic", target_roles=["Engineer"]))
        await db.commit()
    monkeypatch.setattr(outbox, "async_session", sessions)
    yield sessions, uid
    async with sessions() as db:
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_profile_changes_publish_one_task_and_claim_once(database):
    sessions, uid = database

    async def request():
        async with sessions() as db:
            await outbox.request(db, uid)

    with patch.object(outbox, "_publish") as publish:
        await asyncio.gather(*(request() for _ in range(20)))
        publish.assert_called_once()
        ticket = publish.call_args.args[1]
    claims = await asyncio.gather(*(outbox.claim(uid, ticket) for _ in range(20)))
    assert sum(value is not None for value in claims) == 1
    async with sessions() as db:
        row = await db.get(ProfileRescoreRequest, uid)
        assert row.claimed_at is not None


@pytest.mark.asyncio
async def test_edits_during_rescore_get_one_followup_without_losing_latest(database):
    sessions, uid = database
    with patch.object(outbox, "_publish") as publish:
        async with sessions() as db:
            await outbox.request(db, uid)
        ticket = publish.call_args.args[1]
        old_version = await outbox.claim(uid, ticket)
        async with sessions() as db:
            profile = await db.scalar(select(Profile).where(Profile.user_id == uid))
            profile.target_roles = ["Latest role"]
            await outbox.request(db, uid)
        assert publish.call_count == 1
        await outbox.finish(uid, ticket, old_version)
        assert publish.call_count == 2
        new_ticket = publish.call_args.args[1]
        latest_version = await outbox.claim(uid, new_ticket)
        assert latest_version != old_version
        await outbox.finish(uid, new_ticket, latest_version)
        assert publish.call_count == 2
    async with sessions() as db:
        assert await db.get(ProfileRescoreRequest, uid) is None
        profile = await db.scalar(select(Profile).where(Profile.user_id == uid))
        assert profile.target_roles == ["Latest role"]


@pytest.mark.asyncio
async def test_broker_failure_recovers_outbox_and_invalidates_stale_tickets(database):
    sessions, uid = database
    with patch("app.tasks.jobs.rescore_user_jobs.delay", side_effect=ConnectionError("synthetic outage")):
        async with sessions() as db:
            await outbox.request(db, uid)
    async with sessions() as db:
        row = await db.get(ProfileRescoreRequest, uid)
        old_ticket = row.ticket
        row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    with patch.object(outbox, "_publish") as publish:
        assert await outbox.recover() == 1
        publish.assert_called_once()
        new_ticket = publish.call_args.args[1]
    assert await outbox.claim(uid, old_ticket) is None
    assert await outbox.claim(uid, new_ticket) is not None


@pytest.mark.asyncio
async def test_rescore_filters_in_sql_batches_and_preserves_snapshot_time(database, monkeypatch):
    from app.tasks import jobs

    sessions, uid = database
    monkeypatch.setattr(jobs, "async_session", sessions)
    async with sessions() as db:
        profile = await db.scalar(select(Profile).where(Profile.user_id == uid))
        snapshot_time = profile.updated_at
        db.add_all([Job(user_id=uid, title=f"Engineer {i}", company_name="Synthetic", source="synthetic",
                        description="Synthetic engineering role") for i in range(135)])
        await db.commit()
    with patch.object(jobs, "create_notification", new=AsyncMock()):
        first = await jobs._rescore_user_jobs(uid)
        second = await jobs._rescore_user_jobs(uid)
    assert first == {"rescored": 135, "skipped": 0, "errors": 0}
    assert second == {"rescored": 0, "skipped": 0, "errors": 0}
    async with sessions() as db:
        assert set(await db.scalars(select(Job.scored_at).where(Job.user_id == uid))) == {snapshot_time}


@pytest.mark.asyncio
async def test_outbox_rls_and_browser_roles_have_no_access(database):
    sessions, _ = database
    async with sessions() as db:
        assert await db.scalar(text("SELECT relrowsecurity FROM pg_class WHERE oid='profile_rescore_requests'::regclass"))
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not await db.scalar(text("SELECT has_table_privilege(:role,'profile_rescore_requests',:privilege)"),
                                           {"role": role, "privilege": privilege})


@pytest_asyncio.fixture
async def referral_database(database, monkeypatch):
    sessions, _ = database
    campaign_id = f"test-{uuid.uuid4()}"
    monkeypatch.setattr(settings, "referral_campaign_id", campaign_id)
    monkeypatch.setattr(settings, "token_encryption_keys", {"v1": Fernet.generate_key().decode()})
    rows = []

    async def signup(email, **kwargs):
        row = WaitlistSignup(id=uuid.uuid4(), email=email, referral_code=uuid.uuid4().hex[:10].upper(), **kwargs)
        async with sessions() as db:
            db.add(row)
            await db.commit()
        rows.append(row.id)
        return row

    yield sessions, signup
    async with sessions() as db:
        await db.execute(delete(ReferralCredit).where(ReferralCredit.campaign_id == campaign_id))
        await db.execute(delete(ReferralCampaign).where(ReferralCampaign.id == campaign_id))
        await db.execute(update(WaitlistSignup).where(WaitlistSignup.id.in_(rows)).values(referred_by_id=None))
        await db.execute(delete(WaitlistSignup).where(WaitlistSignup.id.in_(rows)))
        await db.commit()


@pytest.mark.asyncio
async def test_concurrent_alias_referrals_earn_one_credit(referral_database):
    sessions, signup = referral_database
    unique = uuid.uuid4().hex
    referrer = await signup(f"ref-{unique}@example.com", email_verified=True)
    invitees = [await signup(email, referred_by_id=referrer.id) for email in (
        f"{unique}+one@gmail.com", f"{unique}+two@googlemail.com", f"{unique[:8]}.{unique[8:]}@gmail.com",
    )]
    tokens = []
    async with sessions() as db:
        await credentials.campaign(db)
        for invitee in invitees:
            tokens.append(await credentials.issue(db, invitee, "exchange"))
        await db.commit()

    async def verify(invitee, token):
        async with sessions() as db:
            return await referral_service.verify_signup(db, invitee.referral_code, token)

    results = await asyncio.gather(*(verify(row, token) for row, token in zip(invitees, tokens)))
    assert all(result is not None for result in results)
    async with sessions() as db:
        assert (await db.get(WaitlistSignup, referrer.id)).verified_referral_count == 1
        assert len(list(await db.scalars(select(ReferralCredit).where(ReferralCredit.referrer_id == referrer.id)))) == 1


@pytest.mark.asyncio
async def test_existing_raw_alias_credits_are_reconciled_before_next_reward(referral_database):
    sessions, signup = referral_database
    unique = uuid.uuid4().hex
    referrer = await signup(f"ref-{unique}@example.com", email_verified=True, verified_referral_count=2)
    aliases = [await signup(f"{unique}+{tag}@gmail.com", email_verified=True, referred_by_id=referrer.id)
               for tag in ("one", "two")]
    async with sessions() as db:
        row, key = await credentials.campaign(db)
        await db.execute(delete(ReferralCredit).where(ReferralCredit.campaign_id == row.id))
        for alias in aliases:
            db.add(ReferralCredit(campaign_id=row.id, fingerprint=credentials.legacy_fingerprint(key, alias.email),
                                  referrer_id=referrer.id))
        row.identity_version = 1  # Actual pre-migration campaign state.
        await db.commit()
    async with sessions() as db:
        row, key = await credentials.campaign(db)
        await db.commit()
        assert row.identity_version == 2
        assert (await db.get(WaitlistSignup, referrer.id)).verified_referral_count == 1

        credits = list(await db.scalars(select(ReferralCredit).where(ReferralCredit.referrer_id == referrer.id)))
        assert len(credits) == 1
        assert credits[0].fingerprint == credentials.fingerprint(key, f"{unique}@gmail.com")
    another = await signup(f"{unique}+three@gmail.com", referred_by_id=referrer.id)
    async with sessions() as db:
        token = await credentials.issue(db, another, "exchange")
        await db.commit()
    async with sessions() as db:
        await referral_service.verify_signup(db, another.referral_code, token)
        assert (await db.get(WaitlistSignup, referrer.id)).verified_referral_count == 1


@pytest.mark.asyncio
async def test_deleted_legacy_identity_cannot_be_replayed_via_unseen_alias(referral_database):
    sessions, signup = referral_database
    unique = uuid.uuid4().hex
    referrer = await signup(f"ref-{unique}@example.com", email_verified=True, verified_referral_count=1)
    async with sessions() as db:
        row, key = await credentials.campaign(db)
        db.add(ReferralCredit(campaign_id=row.id, fingerprint=credentials.legacy_fingerprint(key, f"{unique}+deleted@gmail.com"),
                              referrer_id=referrer.id))
        row.identity_version = 1
        await db.commit()
    alias = await signup(f"{unique}+new@gmail.com", referred_by_id=referrer.id)
    async with sessions() as db:
        token = await credentials.issue(db, alias, "exchange")
        await db.commit()
    async with sessions() as db:
        result = await referral_service.verify_signup(db, alias.referral_code, token)
        assert result[0].email_verified
        assert result[2] is None
        assert (await db.get(WaitlistSignup, referrer.id)).verified_referral_count == 1
        row = await db.get(ReferralCampaign, settings.referral_campaign_id)
        assert row.unresolved_legacy_identities == 1
        assert await db.scalar(select(ReferralCredit.notification_status).where(
            ReferralCredit.campaign_id == row.id, ReferralCredit.fingerprint == credentials.fingerprint(key, alias.email),
        )) == "legacy_review"
