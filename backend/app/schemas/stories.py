"""Pydantic schemas for the Story Bank."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class StoryBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    summary: str | None = None
    situation: str | None = None
    action: str | None = None
    result: str | None = None
    impact_metric: str | None = Field(default=None, max_length=255)
    role_focus: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list)


class StoryCreate(StoryBase):
    pass


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = None
    situation: str | None = None
    action: str | None = None
    result: str | None = None
    impact_metric: str | None = Field(default=None, max_length=255)
    role_focus: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = None


class StoryResponse(StoryBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
