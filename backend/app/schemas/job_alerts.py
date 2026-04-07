"""Pydantic schemas for job alert preferences."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class JobAlertPreferenceResponse(BaseModel):
    """Current job alert configuration."""

    enabled: bool = False
    frequency: str = Field(default="daily", description="immediate | daily | weekly")
    watched_companies: list[str] = Field(default_factory=list)
    use_starred_companies: bool = True
    keyword_filters: list[str] = Field(default_factory=list)
    email_provider: str = Field(default="connected", description="gmail | outlook | connected")
    last_digest_sent_at: str | None = None
    total_alerts_sent: int = 0

    model_config = {"from_attributes": True}


class JobAlertPreferenceUpdate(BaseModel):
    """Partial update for job alert preferences. Only provided fields are updated."""

    enabled: Optional[bool] = None
    frequency: Optional[str] = Field(
        default=None, pattern="^(immediate|daily|weekly)$"
    )
    watched_companies: Optional[list[str]] = None
    use_starred_companies: Optional[bool] = None
    keyword_filters: Optional[list[str]] = None
    email_provider: Optional[str] = Field(
        default=None, pattern="^(gmail|outlook|connected)$"
    )


class JobAlertDigestResult(BaseModel):
    """Result of a digest send attempt."""

    sent: bool
    job_count: int = 0
    provider: str | None = None
    error: str | None = None
