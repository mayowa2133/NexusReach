"""Opt-in real PostgreSQL race tests; use only the disposable audit database."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from cryptography.fernet import Fernet

from app.config import settings
from app.models.user import User
from app.models.person import Person
from app.models.message import Message
from app.models.send_attempt import SendAttempt
from app.models.paid_work import PaidBudgetBucket, PaidReservation
from app.models.referral_security import ReferralCampaign, ReferralCredential, ReferralCredit
from app.models.waitlist import WaitlistSignup
from app.services.draft_staging_service import send_staged_message, cancel_message_schedule
from app.services import paid_work, referral_service
from app.services import paid_context
from app.services.referral_credentials import campaign, issue

pytestmark = pytest.mark.skipif(os.environ.get('NEXUS_SECURITY_DB_TESTS') != '1', reason='requires disposable audit PostgreSQL')
_TEST_FERNET_KEY = Fernet.generate_key().decode()


@pytest_asyncio.fixture
async def database():
    # Fixed loopback endpoint; deliberately cannot target a live database by URL.
    engine = create_async_engine('postgresql+asyncpg://audit:audit-local-only@127.0.0.1:55439/nexusreach_security_audit')
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    uid, pid, mid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with sessions() as db:
        db.add(User(id=uid, email=f'{uid}@example.test'))
        await db.flush()
        db.add(Person(id=pid, user_id=uid, full_name='Synthetic Contact', work_email='recipient@example.test'))
        await db.flush()
        db.add(Message(id=mid, user_id=uid, person_id=pid, channel='email', goal='intro', body='Synthetic', status='staged', scheduled_send_at=datetime.now(timezone.utc)-timedelta(minutes=1)))
        await db.commit()
    yield sessions, uid, mid
    async with sessions() as db:
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_dispatch_calls_provider_once(database):
    sessions, uid, mid = database
    async def provider(**kwargs):
        await asyncio.sleep(0.05)
        return {'message_id': 'synthetic-provider-id'}
    async def send():
        async with sessions() as db:
            try:
                return await send_staged_message(db, user_id=uid, message_id=mid, provider='gmail')
            except HTTPException as exc:
                return exc.status_code
    with patch('app.services.draft_staging_service._send_via_provider', new=AsyncMock(side_effect=provider)) as mock:
        await asyncio.gather(*(send() for _ in range(10)))
        assert mock.await_count == 1
    async with sessions() as db:
        attempts = (await db.scalars(select(SendAttempt).where(SendAttempt.message_id == mid))).all()
        assert len(attempts) == 1
        assert attempts[0].outcome == 'sent'


@pytest.mark.asyncio
async def test_cancelled_generation_never_dispatches(database):
    sessions, uid, mid = database
    async with sessions() as db:
        await cancel_message_schedule(db, user_id=uid, message_id=mid)
    with patch('app.services.draft_staging_service._send_via_provider', new=AsyncMock()) as mock:
        async with sessions() as db:
            with pytest.raises(HTTPException) as exc:
                await send_staged_message(db, user_id=uid, message_id=mid, provider='gmail', scheduled_version=0)
            assert exc.value.status_code == 409
        mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_delivery_cannot_be_retried(database):
    sessions, uid, mid = database
    with patch('app.services.draft_staging_service._send_via_provider', new=AsyncMock(side_effect=TimeoutError)) as mock:
        for _ in range(2):
            async with sessions() as db:
                with pytest.raises(HTTPException):
                    await send_staged_message(db, user_id=uid, message_id=mid, provider='gmail')
        assert mock.await_count == 1
    async with sessions() as db:
        message = await db.get(Message, mid)
        assert message.status == 'delivery_unknown'


@pytest.mark.asyncio
async def test_atomic_paid_reservation_never_exceeds_capacity(database, monkeypatch):
    sessions, uid, _ = database
    monkeypatch.setattr(paid_work, "async_session", sessions)
    async with sessions() as db:
        await db.execute(delete(PaidReservation))
        await db.execute(delete(PaidBudgetBucket))
        await db.commit()
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "daily_api_call_limit", 1)
    monkeypatch.setattr(settings, "global_daily_api_call_limit", 1)
    monkeypatch.setattr(settings, "daily_llm_token_limit", 100)
    monkeypatch.setattr(settings, "global_daily_llm_token_limit", 100)
    monkeypatch.setattr(settings, "account_paid_concurrency", 1)
    monkeypatch.setattr(settings, "global_paid_concurrency", 1)

    async def claim(index: int):
        try:
            return await paid_work.reserve(
                user_id=uid,
                operation_id=f"security-race-{uid}-{index}",
                service="synthetic",
                reserved_tokens=100,
            )
        except HTTPException as exc:
            return exc.status_code

    results = await asyncio.gather(*(claim(index) for index in range(10)))
    assert sum(isinstance(result, PaidReservation) for result in results) == 1
    assert results.count(429) == 9


@pytest.mark.asyncio
async def test_zero_paid_budget_never_invokes_provider(database, monkeypatch):
    sessions, uid, _ = database
    monkeypatch.setattr(paid_work, "async_session", sessions)
    async with sessions() as db:
        await db.execute(delete(PaidReservation))
        await db.execute(delete(PaidBudgetBucket))
        await db.commit()
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "daily_api_call_limit", 0)
    monkeypatch.setattr(settings, "global_daily_api_call_limit", 0)
    monkeypatch.setattr(settings, "daily_llm_token_limit", 100)
    monkeypatch.setattr(settings, "global_daily_llm_token_limit", 100)
    paid_context.set_subject(uid)
    client = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await paid_work.provider_request(
            client,
            "synthetic",
            "GET",
            "https://provider.example.test/resource",
        )

    assert exc.value.status_code == 429
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_referral_exchange_creates_one_credit(monkeypatch):
    monkeypatch.setattr(settings, "token_encryption_keys", {"v1": _TEST_FERNET_KEY})
    engine = create_async_engine(
        'postgresql+asyncpg://audit:audit-local-only@127.0.0.1:55439/nexusreach_security_audit'
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    referrer_id, signup_id = uuid.uuid4(), uuid.uuid4()
    code = uuid.uuid4().hex[:10].upper()
    async with sessions() as db:
        await db.execute(delete(ReferralCredential))
        await db.execute(delete(ReferralCredit))
        await db.execute(delete(ReferralCampaign))
        await db.commit()
        referrer = WaitlistSignup(
            id=referrer_id,
            email=f"ref-{referrer_id}@example.test",
            name="Referrer",
            referral_code=uuid.uuid4().hex[:10].upper(),
            email_verified=True,
        )
        signup = WaitlistSignup(
            id=signup_id,
            email=f"invitee-{signup_id}@example.test",
            name="Invitee",
            referral_code=code,
            referred_by_id=referrer_id,
        )
        db.add_all([referrer, signup])
        await db.flush()
        await campaign(db)
        token = await issue(db, signup, "exchange")
        await db.commit()

    async def consume():
        async with sessions() as db:
            return await referral_service.verify_signup(db, code, token)

    results = await asyncio.gather(*(consume() for _ in range(20)))
    assert sum(result is not None for result in results) == 1
    async with sessions() as db:
        referrer = await db.get(WaitlistSignup, referrer_id)
        credits = list(await db.scalars(select(ReferralCredit).where(
            ReferralCredit.referrer_id == referrer_id
        )))
        assert referrer.verified_referral_count == 1
        assert len(credits) == 1
        await db.execute(delete(WaitlistSignup).where(WaitlistSignup.id.in_([signup_id, referrer_id])))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_and_rejoin_cannot_earn_second_campaign_credit(monkeypatch):
    monkeypatch.setattr(settings, "token_encryption_keys", {"v1": _TEST_FERNET_KEY})
    engine = create_async_engine(
        'postgresql+asyncpg://audit:audit-local-only@127.0.0.1:55439/nexusreach_security_audit'
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    referrer_id = uuid.uuid4()
    email = f"rejoin-{uuid.uuid4()}@example.test"
    async with sessions() as db:
        await db.execute(delete(ReferralCredential))
        await db.execute(delete(ReferralCredit))
        await db.execute(delete(ReferralCampaign))
        await db.commit()
        referrer = WaitlistSignup(
            id=referrer_id,
            email=f"ref-{referrer_id}@example.test",
            name="Referrer",
            referral_code=uuid.uuid4().hex[:10].upper(),
            email_verified=True,
        )
        db.add(referrer)
        await db.flush()
        await campaign(db)
        await db.commit()

    for cycle in range(2):
        signup_id = uuid.uuid4()
        code = uuid.uuid4().hex[:10].upper()
        async with sessions() as db:
            signup = WaitlistSignup(
                id=signup_id,
                email=email,
                name="Invitee",
                referral_code=code,
                referred_by_id=referrer_id,
            )
            db.add(signup)
            await db.flush()
            token = await issue(db, signup, "exchange")
            await db.commit()
        async with sessions() as db:
            assert await referral_service.verify_signup(db, code, token) is not None
            await db.execute(delete(WaitlistSignup).where(WaitlistSignup.id == signup_id))
            await db.commit()

    async with sessions() as db:
        referrer = await db.get(WaitlistSignup, referrer_id)
        assert referrer.verified_referral_count == 1
        await db.execute(delete(WaitlistSignup).where(WaitlistSignup.id == referrer_id))
        await db.commit()
    await engine.dispose()
