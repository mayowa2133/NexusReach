"""SMTP domain probe result tracking — builds a blocklist over time."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SmtpDomainResult(Base):
    """Tracks SMTP probe outcomes per domain (global, not user-scoped).

    Used to build an automatic blocklist: after repeated failures for a domain,
    we skip SMTP verification and fall back to paid tools directly.
    """

    __tablename__ = "smtp_domain_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    # Counters
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    catch_all_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    greylist_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Timestamps
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
