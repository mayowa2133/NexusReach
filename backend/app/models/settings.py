import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    min_message_gap_days: Mapped[int] = mapped_column(Integer, default=7)
    min_message_gap_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    follow_up_suggestion_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    response_rate_warnings_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    guardrails_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    gmail_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    outlook_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    gmail_refresh_token: Mapped[str | None] = mapped_column(Text)
    outlook_refresh_token: Mapped[str | None] = mapped_column(Text)
    linkedin_graph_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    linkedin_graph_source: Mapped[str | None] = mapped_column(Text)
    linkedin_graph_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    linkedin_graph_sync_status: Mapped[str | None] = mapped_column(Text)
    linkedin_graph_last_error: Mapped[str | None] = mapped_column(Text)
    auto_prospect_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_prospect_company_names: Mapped[list | None] = mapped_column(JSONB)
    auto_draft_on_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_stage_on_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_send_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_send_delay_minutes: Mapped[int] = mapped_column(Integer, default=30)
    api_keys: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="settings")  # noqa: F821
