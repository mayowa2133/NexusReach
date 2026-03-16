"""Pydantic schemas for user settings — Phase 9."""

from typing import Optional

from pydantic import BaseModel, Field


class GuardrailsResponse(BaseModel):
    """Current guardrails configuration."""

    min_message_gap_days: int = Field(
        default=7, description="Minimum days between messages to same person"
    )
    min_message_gap_enabled: bool = Field(
        default=True, description="Whether the message gap guardrail is active"
    )
    follow_up_suggestion_enabled: bool = Field(
        default=True, description="Whether follow-up suggestions are shown"
    )
    response_rate_warnings_enabled: bool = Field(
        default=True, description="Whether low response rate warnings are shown"
    )
    guardrails_acknowledged: bool = Field(
        default=False,
        description="True if user has acknowledged disabling any guardrail",
    )
    onboarding_completed: bool = Field(
        default=False,
        description="Whether user has completed the onboarding flow",
    )

    model_config = {"from_attributes": True}


class GuardrailsUpdate(BaseModel):
    """Partial update for guardrails settings. Only provided fields are updated."""

    min_message_gap_days: Optional[int] = Field(
        default=None, ge=1, le=90, description="Minimum days (1–90)"
    )
    min_message_gap_enabled: Optional[bool] = None
    follow_up_suggestion_enabled: Optional[bool] = None
    response_rate_warnings_enabled: Optional[bool] = None


class OnboardingCompleteResponse(BaseModel):
    """Response after marking onboarding as complete."""

    onboarding_completed: bool = True
