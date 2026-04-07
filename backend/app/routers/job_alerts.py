"""Job alerts API routes — manage email notification preferences."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user_id
from app.schemas.job_alerts import (
    JobAlertDigestResult,
    JobAlertPreferenceResponse,
    JobAlertPreferenceUpdate,
)
from app.services.job_alert_service import (
    get_alert_preferences,
    send_digest_for_user,
    update_alert_preferences,
)

router = APIRouter(prefix="/settings/job-alerts", tags=["job-alerts"])


def _to_response(prefs) -> JobAlertPreferenceResponse:
    return JobAlertPreferenceResponse(
        enabled=prefs.enabled,
        frequency=prefs.frequency,
        watched_companies=prefs.watched_companies or [],
        use_starred_companies=prefs.use_starred_companies,
        keyword_filters=prefs.keyword_filters or [],
        email_provider=prefs.email_provider,
        last_digest_sent_at=prefs.last_digest_sent_at.isoformat() if prefs.last_digest_sent_at else None,
        total_alerts_sent=prefs.total_alerts_sent,
    )


@router.get("", response_model=JobAlertPreferenceResponse)
async def get_job_alerts(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return current job alert preferences."""
    prefs = await get_alert_preferences(db, user_id)
    return _to_response(prefs)


@router.put("", response_model=JobAlertPreferenceResponse)
async def update_job_alerts(
    body: JobAlertPreferenceUpdate,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Partially update job alert preferences."""
    payload = body.model_dump(exclude_none=True)
    prefs = await update_alert_preferences(db, user_id, payload)
    return _to_response(prefs)


@router.post("/test", response_model=JobAlertDigestResult)
async def test_job_alert_digest(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Send a test digest immediately (regardless of frequency schedule).

    Useful for verifying the email arrives correctly.
    """
    result = await send_digest_for_user(db, user_id)
    return JobAlertDigestResult(**result)
