"""Email draft staging service."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.settings import UserSettings
from app.services import gmail_service, outlook_service
from app.services.outreach_service import create_outreach_log

logger = logging.getLogger(__name__)


def _message_job_id(message: Message) -> uuid.UUID | None:
    snapshot = message.context_snapshot if isinstance(message.context_snapshot, dict) else {}
    raw_job_id = snapshot.get("job_id")
    if not raw_job_id:
        return None
    try:
        return uuid.UUID(str(raw_job_id))
    except ValueError:
        return None


async def _create_provider_draft(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: str,
    to_email: str,
    subject: str,
    body: str,
) -> dict:
    if provider == "gmail":
        return await gmail_service.create_draft(
            db=db,
            user_id=user_id,
            to_email=to_email,
            subject=subject,
            body=body,
        )
    if provider == "outlook":
        return await outlook_service.create_draft(
            db=db,
            user_id=user_id,
            to_email=to_email,
            subject=subject,
            body=body,
        )
    raise ValueError("Invalid provider. Use 'gmail' or 'outlook'.")


async def _ensure_outreach_log(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    message_id: uuid.UUID,
    provider: str,
    job_id: uuid.UUID | None,
    provider_draft_id: str | None = None,
    provider_message_id: str | None = None,
) -> OutreachLog:
    result = await db.execute(
        select(OutreachLog).where(
            OutreachLog.user_id == user_id,
            OutreachLog.message_id == message_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        # Refresh provider tracking so reconciliation picks up re-staged drafts.
        existing.provider = provider
        if provider_draft_id:
            existing.provider_draft_id = provider_draft_id
        if provider_message_id:
            existing.provider_message_id = provider_message_id
        return existing

    log = await create_outreach_log(
        db=db,
        user_id=user_id,
        person_id=person_id,
        job_id=job_id,
        message_id=message_id,
        status="draft",
        channel="email",
        notes=f"Draft staged in {provider}.",
    )
    log.provider = provider
    log.provider_draft_id = provider_draft_id
    log.provider_message_id = provider_message_id
    return log


async def stage_message_draft(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
    provider: str,
) -> dict:
    """Stage one message draft and create/update its outreach tracking."""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        raise ValueError("Message not found.")
    if message.channel != "email":
        raise ValueError("Only email messages can be staged as drafts.")

    result = await db.execute(select(Person).where(Person.id == message.person_id))
    person = result.scalar_one_or_none()
    if not person or not person.work_email:
        raise ValueError("Recipient has no email address. Use the email finder first.")

    subject = message.subject or "No subject"
    draft = await _create_provider_draft(
        db=db,
        user_id=user_id,
        provider=provider,
        to_email=person.work_email,
        subject=subject,
        body=message.body,
    )

    message.status = "staged"
    outreach_log = await _ensure_outreach_log(
        db=db,
        user_id=user_id,
        person_id=person.id,
        message_id=message.id,
        provider=provider,
        job_id=_message_job_id(message),
        provider_draft_id=draft.get("draft_id"),
        provider_message_id=draft.get("message_id"),
    )
    await db.commit()

    return {
        "draft_id": draft["draft_id"],
        "provider": provider,
        "message_id": draft.get("message_id"),
        "outreach_log_id": str(outreach_log.id),
        "person_id": str(person.id),
    }


async def stage_message_drafts(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    message_ids: list[uuid.UUID],
    provider: str,
) -> dict:
    """Stage multiple message drafts sequentially with per-item results."""
    items: list[dict] = []
    staged_count = 0
    failed_count = 0

    for message_id in message_ids:
        try:
            result = await stage_message_draft(
                db=db,
                user_id=user_id,
                message_id=message_id,
                provider=provider,
            )
            items.append(
                {
                    "message_id": str(message_id),
                    "person_id": result["person_id"],
                    "draft_id": result["draft_id"],
                    "provider": provider,
                    "outreach_log_id": result["outreach_log_id"],
                    "status": "staged",
                    "error": None,
                }
            )
            staged_count += 1
        except ValueError as exc:
            failed_count += 1
            items.append(
                {
                    "message_id": str(message_id),
                    "person_id": None,
                    "draft_id": None,
                    "provider": provider,
                    "outreach_log_id": None,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return {
        "requested_count": len(message_ids),
        "staged_count": staged_count,
        "failed_count": failed_count,
        "items": items,
    }


async def resolve_connected_provider(
    db: AsyncSession, user_id: uuid.UUID,
) -> str | None:
    """Return 'gmail' or 'outlook' if connected, else None."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        return None
    if settings.gmail_connected and settings.gmail_refresh_token:
        return "gmail"
    if settings.outlook_connected and settings.outlook_refresh_token:
        return "outlook"
    return None


async def _send_via_provider(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: str,
    to_email: str,
    subject: str,
    body: str,
) -> dict:
    if provider == "gmail":
        return await gmail_service.send_message(
            db=db,
            user_id=user_id,
            to_email=to_email,
            subject=subject,
            body=body,
        )
    if provider == "outlook":
        return await outlook_service.send_message(
            db=db,
            user_id=user_id,
            to_email=to_email,
            subject=subject,
            body=body,
        )
    raise ValueError("Invalid provider. Use 'gmail' or 'outlook'.")


async def send_staged_message(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
    provider: str | None = None,
) -> dict:
    """Send a staged message via connected email provider.

    Updates message status to 'sent' and outreach log status.
    """
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        raise ValueError("Message not found.")
    if message.status == "sent":
        raise ValueError("Message already sent.")
    if message.channel != "email":
        raise ValueError("Only email messages can be sent.")

    result = await db.execute(select(Person).where(Person.id == message.person_id))
    person = result.scalar_one_or_none()
    if not person or not person.work_email:
        raise ValueError("Recipient has no email address.")

    if not provider:
        provider = await resolve_connected_provider(db, user_id)
    if not provider:
        raise ValueError("No email provider connected. Connect Gmail or Outlook in Settings.")

    subject = message.subject or "No subject"
    send_result = await _send_via_provider(
        db=db,
        user_id=user_id,
        provider=provider,
        to_email=person.work_email,
        subject=subject,
        body=message.body,
    )

    message.status = "sent"
    message.scheduled_send_at = None

    # Update outreach log if exists
    outreach_result = await db.execute(
        select(OutreachLog).where(
            OutreachLog.user_id == user_id,
            OutreachLog.message_id == message_id,
        )
    )
    outreach_log = outreach_result.scalar_one_or_none()
    if outreach_log:
        from datetime import datetime, timezone  # noqa: PLC0415

        outreach_log.status = "sent"
        outreach_log.sent_at = datetime.now(timezone.utc)
        outreach_log.last_contacted_at = outreach_log.sent_at
        if send_result.get("message_id"):
            outreach_log.provider_message_id = send_result["message_id"]

    await db.commit()

    return {
        "message_id": str(message_id),
        "provider": provider,
        "status": "sent",
        "provider_message_id": send_result.get("message_id", ""),
    }
