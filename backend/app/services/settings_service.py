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
    "onboarding_completed",
)

TOGGLE_FIELDS = (
    "min_message_gap_enabled",
    "follow_up_suggestion_enabled",
    "response_rate_warnings_enabled",
)

AUTO_PROSPECT_FIELDS = (
    "auto_prospect_enabled",
    "auto_prospect_company_names",
    "auto_draft_on_apply",
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
            "onboarding_completed": False,
        }

    return {field: getattr(settings, field) for field in GUARDRAIL_FIELDS}


async def get_auto_prospect(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Return current auto-prospect settings for a user."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        return {
            "auto_prospect_enabled": False,
            "auto_prospect_company_names": None,
            "auto_draft_on_apply": False,
        }

    return {field: getattr(settings, field) for field in AUTO_PROSPECT_FIELDS}


async def update_auto_prospect(
    db: AsyncSession, user_id: uuid.UUID, payload: dict,
) -> dict:
    """Partially update auto-prospect settings."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.flush()

    for key, value in payload.items():
        if key in AUTO_PROSPECT_FIELDS and value is not None:
            setattr(settings, key, value)

    await db.commit()
    await db.refresh(settings)

    return {field: getattr(settings, field) for field in AUTO_PROSPECT_FIELDS}


async def is_auto_prospect_enabled(
    db: AsyncSession, user_id: uuid.UUID, company_name: str | None = None,
) -> bool:
    """Check if auto-prospect is enabled, optionally for a specific company."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if not settings or not settings.auto_prospect_enabled:
        return False

    # null company list = all companies
    if not settings.auto_prospect_company_names:
        return True

    if not company_name:
        return True

    # Check if company matches any in the list (case-insensitive)
    company_lower = company_name.lower().strip()
    return any(
        name.lower().strip() == company_lower
        for name in settings.auto_prospect_company_names
    )


async def complete_onboarding(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Mark onboarding as complete for a user."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.flush()

    settings.onboarding_completed = True
    await db.commit()


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
