"""Pydantic schemas for the next-action / cadence engine."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class NextActionResponse(BaseModel):
    kind: str
    urgency: str
    reason: str
    suggested_channel: str | None = None
    suggested_goal: str | None = None
    job_id: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    person_id: str | None = None
    person_name: str | None = None
    message_id: str | None = None
    outreach_id: str | None = None
    age_days: float | None = None
    deep_link: str | None = None
    meta: dict[str, Any] = {}


class NextActionListResponse(BaseModel):
    items: list[NextActionResponse]
    total: int
