"""Job alert preferences model — email notifications for new job postings."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobAlertPreference(Base):
    __tablename__ = "job_alert_preferences"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if "enabled" not in kwargs:
            self.enabled = False
        if "frequency" not in kwargs:
            self.frequency = "daily"
        if "watched_companies" not in kwargs:
            self.watched_companies = []
        if "use_starred_companies" not in kwargs:
            self.use_starred_companies = True
        if "keyword_filters" not in kwargs:
            self.keyword_filters = []
        if "email_provider" not in kwargs:
            self.email_provider = "connected"
        if "total_alerts_sent" not in kwargs:
            self.total_alerts_sent = 0

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    # Global toggle — disabling pauses all email alerts without losing config
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Digest frequency: "immediate" | "daily" | "weekly"
    frequency: Mapped[str] = mapped_column(String(20), default="daily")

    # Watched company names (case-insensitive matching).
    # Empty list + use_starred_companies=True means "only starred companies".
    watched_companies: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list  # noqa: F821
    )

    # If true, automatically include the user's starred companies in alerts
    use_starred_companies: Mapped[bool] = mapped_column(Boolean, default=True)

    # Optional keyword filters — when non-empty, jobs must match at least one keyword
    keyword_filters: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list  # noqa: F821
    )

    # Email delivery preference: "gmail" | "outlook" | "connected"
    # "connected" means whichever provider is connected (Gmail preferred)
    email_provider: Mapped[str] = mapped_column(String(20), default="connected")

    # Tracking — last time a digest email was sent
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # How many alerts have been sent total
    total_alerts_sent: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
