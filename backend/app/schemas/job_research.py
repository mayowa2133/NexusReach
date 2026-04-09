"""Schemas for job auto research state and snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.people import (
    CompanyResponse,
    JobContextResponse,
    PersonResponse,
    SearchErrorDetail,
)
from app.schemas.linkedin_graph import LinkedInGraphConnectionResponse

JobResearchStatus = Literal["not_configured", "queued", "running", "completed", "failed"]


class JobResearchResponse(BaseModel):
    status: JobResearchStatus
    enabled_for_company: bool = False
    auto_find_emails: bool = False
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    company: CompanyResponse | None = None
    your_connections: list[LinkedInGraphConnectionResponse] = []
    recruiters: list[PersonResponse] = []
    hiring_managers: list[PersonResponse] = []
    peers: list[PersonResponse] = []
    job_context: JobContextResponse | None = None
    errors: list[SearchErrorDetail] | None = None
    email_attempted_count: int = 0
    email_found_count: int = 0


class JobResearchRunRequest(BaseModel):
    target_count_per_bucket: int = Field(default=3, ge=1, le=10)
