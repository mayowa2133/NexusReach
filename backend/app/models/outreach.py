import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OutreachLog(Base):
    __tablename__ = "outreach_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(50), default="draft"
    )  # draft | sent | connected | responded | met | following_up | closed
    channel: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # linkedin_note | linkedin_message | email | phone | in_person | other

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_follow_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    response_received: Mapped[bool] = mapped_column(Boolean, default=False)

    # Provider-side tracking for post-send reconciliation.
    # Populated when a draft is staged to Gmail/Outlook; used by the
    # reconcile job to detect when the user actually sends from the
    # provider UI so outreach status can flip from "draft" to "sent".
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_draft_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    person: Mapped["Person"] = relationship()  # noqa: F821
    job: Mapped["Job"] = relationship()  # noqa: F821
    message: Mapped["Message"] = relationship()  # noqa: F821
