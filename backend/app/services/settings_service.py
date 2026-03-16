"""Service layer for user settings — Phase 9."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import UserSettings


GUARDRAIL_FIELDS = (
    "min_message_gap_days",
    "min_message_gap_enabled",
    "follow_up_suggestion_enabled",
    "response_rate_warnings_enabled",
    "guardrails_acknowledged",
)

TOGGLE_FIELDS = (
    "min_message_gap_enabled",
    "follow_up_suggestion_enabled",
    "response_rate_warnings_enabled",
)


async def get_guardrails(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Return current guardrails settings for a user."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Return defaults (auto-created row should exist, but be safe)
        return {
            "min_message_gap_days": 7,
            "min_message_gap_enabled": True,
            "follow_up_suggestion_enabled": True,
            "response_rate_warnings_enabled": True,
            "guardrails_acknowledged": False,
        }

    return {field: getattr(settings, field) for field in GUARDRAIL_FIELDS}


async def update_guardrails(
    db: AsyncSession, user_id: uuid.UUID, payload: dict
) -> dict:
    """Partially update guardrails settings. Returns the full updated state.

    Automatically sets ``guardrails_acknowledged = True`` when any toggle is
    turned off, so the dashboard can show the "Guardrails: Modified" badge.
    """
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.flush()

    # Apply provided fields
    for key, value in payload.items():
        if value is not None:
            setattr(settings, key, value)

    # Auto-acknowledge if any guardrail is being disabled
    any_disabled = any(
        getattr(settings, field) is False for field in TOGGLE_FIELDS
    )
    if any_disabled:
        settings.guardrails_acknowledged = True
    else:
        # All guardrails re-enabled → clear acknowledged flag
        settings.guardrails_acknowledged = False

    await db.commit()
    await db.refresh(settings)

    return {field: getattr(settings, field) for field in GUARDRAIL_FIELDS}
