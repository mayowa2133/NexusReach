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


class AutoProspectResponse(BaseModel):
    """Current auto-prospect configuration."""

    auto_prospect_enabled: bool = Field(
        default=False,
        description="Auto-find people and emails when new jobs arrive",
    )
    auto_prospect_company_names: list[str] | None = Field(
        default=None,
        description="Company names to auto-prospect for. null = all companies.",
    )
    auto_draft_on_apply: bool = Field(
        default=False,
        description="Auto-draft outreach emails when marking a job as applied",
    )
    auto_stage_on_apply: bool = Field(
        default=False,
        description="Auto-stage drafted emails to inbox when applying",
    )
    auto_send_enabled: bool = Field(
        default=False,
        description="Auto-send staged emails after a delay",
    )
    auto_send_delay_minutes: int = Field(
        default=30,
        description="Delay in minutes before auto-sending staged emails",
    )

    model_config = {"from_attributes": True}


class AutoProspectUpdate(BaseModel):
    """Partial update for auto-prospect settings."""

    auto_prospect_enabled: Optional[bool] = None
    auto_prospect_company_names: Optional[list[str]] = None
    auto_draft_on_apply: Optional[bool] = None
    auto_stage_on_apply: Optional[bool] = None
    auto_send_enabled: Optional[bool] = None
    auto_send_delay_minutes: Optional[int] = Field(
        default=None, ge=5, le=1440, description="Delay in minutes (5–1440)"
    )


class CadenceSettingsResponse(BaseModel):
    draft_unsent_threshold_hours: int = Field(default=24, description="Flag unsent drafts older than N hours")
    awaiting_reply_threshold_days: int = Field(default=5, description="Follow-up after N days with no reply")
    applied_untouched_threshold_days: int = Field(default=7, description="Nudge after applying with no outreach for N days")
    thank_you_window_hours: int = Field(default=48, description="Thank-you window after interview round (hours)")
    cadence_digest_enabled: bool = Field(default=True, description="Send weekly cadence digest email")

    model_config = {"from_attributes": True}


class CadenceSettingsUpdate(BaseModel):
    draft_unsent_threshold_hours: Optional[int] = Field(default=None, ge=1, le=168)
    awaiting_reply_threshold_days: Optional[int] = Field(default=None, ge=1, le=30)
    applied_untouched_threshold_days: Optional[int] = Field(default=None, ge=1, le=60)
    thank_you_window_hours: Optional[int] = Field(default=None, ge=1, le=168)
    cadence_digest_enabled: Optional[bool] = None
