"""Mailbox proof, single-use exchanges and campaign-lifetime referral credits."""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.models.referral_security import ReferralCampaign, ReferralCredential, ReferralCredit
from app.models.waitlist import WaitlistSignup
from app.services.oauth_token_crypto import _fernet_for_version


def fingerprint(key: bytes, email: str) -> str:
    return hmac.new(key, email.strip().lower().encode(), hashlib.sha256).hexdigest()


async def campaign(db):
    # Serialize initialization/backfill across API and worker processes.
    await db.execute(text('SELECT pg_advisory_xact_lock(71620371)'))
    row = await db.get(ReferralCampaign, settings.referral_campaign_id)
    if row is None:
        version = settings.token_encryption_primary_version
        try:
            key = secrets.token_bytes(32)
            sealed = _fernet_for_version(version).encrypt(key).decode()
        except ValueError:
            raise HTTPException(503, 'Referral security configuration unavailable') from None
        row = ReferralCampaign(
            id=settings.referral_campaign_id,
            sealed_key=version + ":" + sealed,
            legacy_until=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(row)
        await db.flush()
        # Seed anti-replay records without modifying existing earned totals.
        existing = (await db.execute(select(WaitlistSignup).where(WaitlistSignup.email_verified.is_(True)))).scalars().all()
        for signup in existing:
            await db.execute(
                insert(ReferralCredit)
                .values(
                    id=uuid.uuid4(),
                    campaign_id=row.id,
                    fingerprint=fingerprint(key, signup.email),
                    referrer_id=signup.referred_by_id,
                    notification_status="legacy",
                )
                .on_conflict_do_nothing()
            )
    if row.closed_at is not None or not row.sealed_key:
        raise HTTPException(503, 'Referral campaign is closed')
    version, sealed = row.sealed_key.split(':', 1)
    return row, _fernet_for_version(version).decrypt(sealed.encode())


async def legacy_allowed(db) -> bool:
    """Allow old query-token records for seven days after campaign bootstrap."""
    row, _ = await campaign(db)
    return datetime.now(timezone.utc) < row.legacy_until


async def issue(db, signup, kind):
    from app.services.referral_service import hash_token, mint_access_token, mint_verification_token
    now = datetime.now(timezone.utc)
    token = mint_access_token() if kind == 'owner' else mint_verification_token()
    if kind == 'owner':
        existing = (await db.execute(select(ReferralCredential).where(
            ReferralCredential.signup_id == signup.id, ReferralCredential.kind == 'owner'
        ).order_by(ReferralCredential.created_at.desc()))).scalars().all()
        for stale in existing[2:]:
            await db.delete(stale)
    db.add(ReferralCredential(token_hash=hash_token(token), signup_id=signup.id, kind=kind,
        expires_at=now+timedelta(days=7) if kind == 'owner' else now+timedelta(minutes=30)))
    return token


async def recovery_allowed(db, email):
    from app.utils.discovery_rate_limit import _client
    _, key = await campaign(db)
    recipient = fingerprint(key, email)
    if settings.environment in {'test', 'e2e'}:
        return True
    try:
        allowed = await _client().eval('''
          if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
          local now = tonumber(ARGV[1])
          redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now-86400)
          redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now-3600)
          if redis.call('ZCARD', KEYS[2]) >= 3 or redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[3]) then return 0 end
          redis.call('SET', KEYS[1], '1', 'EX', 600)
          redis.call('ZADD', KEYS[2], now, ARGV[2])
          redis.call('EXPIRE', KEYS[2], 86460)
          redis.call('ZADD', KEYS[3], now, ARGV[2])
          redis.call('EXPIRE', KEYS[3], 3660)
          return 1
        ''', 3, 'nr:recover:cooldown:'+recipient, 'nr:recover:day:'+recipient,
            'nr:recover:global', datetime.now(timezone.utc).timestamp(), secrets.token_hex(16), settings.referral_recovery_hourly_limit)
        return allowed == 1
    except Exception:
        raise HTTPException(503, 'Recovery temporarily unavailable') from None


async def purge_campaign_credentials(db):
    now = datetime.now(timezone.utc)
    await db.execute(delete(ReferralCredential).where(ReferralCredential.expires_at <= now))
    rows = (await db.execute(select(ReferralCampaign).where(ReferralCampaign.closed_at < now-timedelta(days=30)))).scalars().all()
    for row in rows:
        await db.execute(delete(ReferralCredit).where(ReferralCredit.campaign_id == row.id))
        row.sealed_key = None
    await db.commit()
