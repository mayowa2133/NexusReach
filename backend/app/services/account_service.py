"""Account export and deletion helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.api_usage import ApiUsage
from app.models.company import Company
from app.models.interview_prep_brief import InterviewPrepBrief
from app.models.job import Job
from app.models.job_alert import JobAlertPreference
from app.models.job_research_snapshot import JobResearchSnapshot
from app.models.linkedin_graph import (
    LinkedInGraphConnection,
    LinkedInGraphFollow,
    LinkedInGraphSyncRun,
)
from app.models.message import Message
from app.models.notification import Notification
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.profile import Profile
from app.models.resume_artifact import ResumeArtifact
from app.models.search_log import SearchLog
from app.models.search_preference import SearchPreference
from app.models.settings import UserSettings
from app.models.story import Story
from app.models.tailored_resume import TailoredResume
from app.models.user import User


class AccountDeletionUnavailableError(RuntimeError):
    """Raised when account deletion cannot safely complete."""


EXPORT_MODELS = [
    Profile,
    UserSettings,
    Company,
    Job,
    Person,
    Message,
    OutreachLog,
    Notification,
    SearchPreference,
    SearchLog,
    ApiUsage,
    LinkedInGraphConnection,
    LinkedInGraphFollow,
    LinkedInGraphSyncRun,
    JobAlertPreference,
    JobResearchSnapshot,
    TailoredResume,
    ResumeArtifact,
    Story,
    InterviewPrepBrief,
]

DELETE_ORDER = [
    OutreachLog,
    Message,
    ResumeArtifact,
    TailoredResume,
    InterviewPrepBrief,
    JobResearchSnapshot,
    SearchLog,
    Notification,
    Person,
    Job,
    Company,
    SearchPreference,
    ApiUsage,
    LinkedInGraphConnection,
    LinkedInGraphFollow,
    LinkedInGraphSyncRun,
    JobAlertPreference,
    Story,
    Profile,
    UserSettings,
]

SENSITIVE_EXPORT_FIELDS = {
    "gmail_refresh_token",
    "outlook_refresh_token",
    "api_keys",
}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    return value


def _serialize_row(row: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if column.name in SENSITIVE_EXPORT_FIELDS and value:
            payload[column.name] = "[redacted]"
        else:
            payload[column.name] = _serialize_value(value)
    return payload


async def export_user_data(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    tables: dict[str, list[dict[str, Any]]] = {}
    if user is not None:
        tables[User.__tablename__] = [_serialize_row(user)]
    else:
        tables[User.__tablename__] = []

    for model in EXPORT_MODELS:
        result = await db.execute(select(model).where(model.user_id == user_id))
        rows = result.scalars().all()
        tables[model.__tablename__] = [_serialize_row(row) for row in rows]

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "user_id": str(user_id),
        "format_version": 1,
        "redacted_fields": sorted(SENSITIVE_EXPORT_FIELDS),
        "tables": tables,
    }


async def delete_user_data(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    deleted: dict[str, int] = {}
    try:
        for model in DELETE_ORDER:
            result = await db.execute(delete(model).where(model.user_id == user_id))
            deleted[model.__tablename__] = int(result.rowcount or 0)

        user_result = await db.execute(delete(User).where(User.id == user_id))
        deleted[User.__tablename__] = int(user_result.rowcount or 0)
        await db.commit()
        return deleted
    except Exception:
        await db.rollback()
        raise


async def delete_supabase_auth_user(user_id: uuid.UUID) -> bool:
    if settings.auth_mode == "dev":
        return False

    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise AccountDeletionUnavailableError(
            "Supabase service role key is required to delete auth identities."
        )

    base_url = settings.supabase_url.rstrip("/")
    url = f"{base_url}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.delete(url, headers=headers)

    if response.status_code in {200, 204, 404}:
        return True

    raise AccountDeletionUnavailableError(
        f"Supabase auth deletion failed with status {response.status_code}."
    )
