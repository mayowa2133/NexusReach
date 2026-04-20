"""Pydantic schemas for the Interview-Prep Workspace."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LikelyRound(BaseModel):
    name: str
    type: str  # recruiter_screen | technical | system_design | behavioral | onsite | panel | case
    description: str | None = None
    inferred: bool = True


class QuestionCategory(BaseModel):
    key: str  # behavioral | technical | system_design | culture_fit | role_specific
    label: str
    examples: list[str] = Field(default_factory=list)
    inferred: bool = True


class PrepTheme(BaseModel):
    title: str
    reason: str | None = None
    inferred: bool = True


class StoryMapping(BaseModel):
    category: str  # matches QuestionCategory.key
    story_ids: list[UUID] = Field(default_factory=list)


class InterviewPrepBriefResponse(BaseModel):
    id: UUID
    job_id: UUID
    company_overview: str | None = None
    role_summary: str | None = None
    likely_rounds: list[LikelyRound] = Field(default_factory=list)
    question_categories: list[QuestionCategory] = Field(default_factory=list)
    prep_themes: list[PrepTheme] = Field(default_factory=list)
    story_map: list[StoryMapping] = Field(default_factory=list)
    sourced_signals: dict | None = None
    user_notes: str | None = None
    generated_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InterviewPrepGenerateRequest(BaseModel):
    regenerate: bool = False


class InterviewPrepUpdate(BaseModel):
    user_notes: str | None = None
    story_map: list[StoryMapping] | None = None
