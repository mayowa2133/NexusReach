"""Durable, idempotent erasure. Failed storage work always retains its pointer."""
import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from app.config import settings
from app.models.deletion import AuthTombstone, DeletionRequest, DeletionAction
from app.services.identity_lifecycle import lock_subject

logger = logging.getLogger(__name__)
_development_receipt_key = secrets.token_bytes(32)


def tombstone_retention() -> timedelta:
    """Keep revocation state for 30 days and beyond the longest access JWT."""
    return max(
        timedelta(days=30),
        timedelta(seconds=settings.supabase_access_token_max_lifetime_seconds)
        + timedelta(days=1),
    )


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _receipt(scope: str, request_key: str) -> str:
    configured = settings.deletion_receipt_hmac_key.encode("utf-8")
    key = configured or _development_receipt_key
    value = hmac.new(
        key,
        f"{scope}:{request_key}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded = base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return "nrd_" + encoded


async def begin_request(db, scope: str, request_key: str | None, actions: list[tuple[str, str]]):
    key = request_key or secrets.token_urlsafe(32)
    if not 32 <= len(key) <= 128:
        raise HTTPException(422, 'Idempotency key must contain 32–128 characters')
    receipt = _receipt(scope, key)
    request_hash = digest(scope + ':' + key)
    existing = (await db.execute(select(DeletionRequest).where(DeletionRequest.request_hash == request_hash))).scalar_one_or_none()
    if existing:
        return existing, receipt
    row = DeletionRequest(request_hash=request_hash, receipt_hash=digest(receipt), status='pending')
    db.add(row)
    await db.flush()
    for kind, target in actions:
        db.add(DeletionAction(request_id=row.id, kind=kind, target=target, status='pending', attempts=0))
    return row, receipt


def receipt_response(row, receipt):
    return {'status': row.status, 'request_id': str(row.id), 'receipt_token': receipt}


async def delete_waitlist(db, signup, request_key=None):
    # Lock survives signup deletion until the outbox and local delete commit.
    await lock_subject(db, signup.id)
    actions = [('storage', signup.resume_path)] if signup.resume_path else []
    if settings.waitlist_sheet_mirror_url:
        actions.append(('sheet', signup.email))
    row, receipt = await begin_request(db, 'waitlist:' + str(signup.id), request_key, actions)
    await db.delete(signup)
    await db.commit()
    return receipt_response(row, receipt)


async def process_deletions(db):
    from app.clients import supabase_storage_client, sheets_mirror_client
    from app.services.account_service import delete_supabase_auth_user
    now = datetime.now(timezone.utc)
    rows = (await db.execute(select(DeletionAction).where(
        DeletionAction.status == 'pending', DeletionAction.next_attempt_at <= now
    ).order_by(DeletionAction.next_attempt_at).limit(50).with_for_update(skip_locked=True))).scalars().all()
    for action in rows:
        succeeded = False
        try:
            if action.kind == 'storage':
                succeeded = await supabase_storage_client.delete_object(action.target)
            elif action.kind == 'auth':
                subject = uuid.UUID(action.target)
                succeeded = await delete_supabase_auth_user(subject)
                succeeded = succeeded or (settings.auth_mode == "dev" and settings.dev_auth_bypass_enabled)
                if succeeded:
                    await db.execute(update(AuthTombstone).where(AuthTombstone.subject == subject).values(upstream_deleted_at=now))
            elif action.kind == 'sheet':
                succeeded = await sheets_mirror_client.delete_signup(action.target)
        except Exception:
            logger.warning('External deletion pending: action=%s kind=%s', action.id, action.kind)
        action.attempts += 1
        if succeeded:
            action.status = 'completed'
            action.target = None
        else:
            seconds = (60, 300, 1800)[action.attempts-1] if action.attempts <= 3 else 21600
            action.next_attempt_at = now + timedelta(seconds=seconds)
    await db.flush()
    pending = select(DeletionAction.request_id).where(DeletionAction.status == 'pending')
    await db.execute(update(DeletionRequest).where(DeletionRequest.status == 'pending', ~DeletionRequest.id.in_(pending)).values(status='completed', completed_at=now))
    overdue = await db.scalar(select(DeletionRequest.id).where(DeletionRequest.status == 'pending', DeletionRequest.created_at < now-timedelta(days=1)).limit(1))
    if overdue:
        logger.error('Deletion backlog exceeds 24 hours')
    await db.execute(delete(DeletionRequest).where(DeletionRequest.completed_at < now-timedelta(days=30)))
    await db.execute(
        delete(AuthTombstone).where(
            AuthTombstone.upstream_deleted_at < now - tombstone_retention()
        )
    )
    await db.commit()
