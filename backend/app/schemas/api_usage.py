"""Pydantic schemas for API usage tracking."""

from pydantic import BaseModel, Field


class DailyUsageResponse(BaseModel):
    """Summary of today's API usage for the current user."""

    total_calls: int = Field(description="Total API calls made today")
    total_tokens_in: int = Field(description="Total input tokens used today")
    total_tokens_out: int = Field(description="Total output tokens used today")
    total_cost_cents: int = Field(description="Estimated cost in cents today")
    daily_call_limit: int = Field(description="Maximum API calls per day")
    daily_token_limit: int = Field(description="Maximum Claude tokens per day")
    calls_remaining: int = Field(description="API calls remaining today")
    tokens_remaining: int = Field(description="Claude tokens remaining today")


class UsageRecordResponse(BaseModel):
    """Single usage record."""

    id: str
    service: str
    endpoint: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_cents: int | None = None
    created_at: str

    model_config = {"from_attributes": True}
