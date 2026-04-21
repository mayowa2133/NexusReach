"""Pydantic schemas for batch triage / networking ROI."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TriageDimensions(BaseModel):
    """Per-dimension breakdown of the ROI score (each 0–100)."""

    job_fit: float = Field(description="Match score against profile")
    contactability: float = Field(description="Verified contacts found at this company")
    warm_path: float = Field(description="LinkedIn warm-path connections present")
    outreach_opportunity: float = Field(description="Open outreach opportunity window")
    stage_momentum: float = Field(description="How active the pipeline stage is")


class TriageJobSummary(BaseModel):
    """Minimal job fields needed to render a triage row."""

    id: str
    title: str | None
    company_name: str | None
    stage: str
    match_score: float | None
    starred: bool
    tags: list[str] | None
    applied_at: str | None
    url: str | None


class TriageResult(BaseModel):
    """Single job triage row with ROI score and explanation."""

    job: TriageJobSummary
    roi_score: float = Field(description="Overall networking ROI score (0–100)")
    roi_tier: str = Field(description="high | medium | low | skip")
    dimensions: TriageDimensions
    recommended_action: str
    verified_contacts: int = Field(default=0)
    warm_path_contacts: int = Field(default=0)
    outreach_sent: int = Field(default=0)
    has_active_conversation: bool = Field(default=False)


class TriageResponse(BaseModel):
    """Full triage response — sorted by roi_score descending."""

    items: list[TriageResult]
    total: int
    high_count: int
    medium_count: int
    low_count: int
    skip_count: int
