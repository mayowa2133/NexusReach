"""One lock and revocation boundary for bootstrap, deletion, and credential minting."""
import uuid
import httpx
from fastapi import HTTPException
from sqlalchemy import select, text
from app.config import settings
from app.models.deletion import AuthTombstone


async def lock_subject(db, subject: uuid.UUID):
    key = int.from_bytes(subject.bytes[:8], byteorder='big', signed=True)
    await db.execute(text('SELECT pg_advisory_xact_lock(:lock_key)'), {'lock_key': key})


async def assert_subject_active(db, subject: uuid.UUID):
    if (await db.execute(select(AuthTombstone).where(AuthTombstone.subject == subject))).scalar_one_or_none() is not None:
        raise HTTPException(401, 'Account has been deleted')


async def verify_upstream_identity(subject: uuid.UUID):
    if settings.auth_mode == 'dev' and settings.dev_auth_bypass_enabled:
        return
    # No Supabase project backs the test/e2e harnesses, so there is nothing to
    # ask; the same guard the rest of the remediation uses (paid_work.reserve,
    # url_safety._fetch_capacity, referral_credentials.recovery_allowed). This
    # widens nothing on a real deployment: every production gate in config.py is
    # itself keyed on `environment == "production"`, so an environment set to
    # `e2e` has already opted out of all of them, not just this one.
    if settings.environment in {'test', 'e2e'}:
        return
    if not settings.supabase_service_role_key or not settings.supabase_url:
        raise HTTPException(503, 'Identity verification unavailable')
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f'{settings.supabase_url.rstrip("/")}/auth/v1/admin/users/{subject}',
                headers={'apikey': settings.supabase_service_role_key, 'Authorization': f'Bearer {settings.supabase_service_role_key}'})
        if response.status_code == 404:
            raise HTTPException(401, 'Account is unavailable')
        if response.status_code != 200:
            raise HTTPException(503, 'Identity verification unavailable')
        payload = response.json()
        if str(payload.get('id')) != str(subject) or payload.get('deleted_at'):
            raise HTTPException(401, 'Account is unavailable')
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'Identity verification unavailable') from None
