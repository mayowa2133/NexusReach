import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE")
    )

    # Message content
    channel: Mapped[str] = mapped_column(String(50))  # linkedin_note | linkedin_message | email | follow_up | thank_you
    goal: Mapped[str] = mapped_column(String(100))  # intro | coffee_chat | referral | informational | follow_up | thank_you
    subject: Mapped[str | None] = mapped_column(String(500))  # email subject line
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # AI metadata
    reasoning: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(100))
    token_usage: Mapped[dict | None] = mapped_column(JSONB)

    # Context snapshot — what the AI saw when drafting
    context_snapshot: Mapped[dict | None] = mapped_column(JSONB)

    # Status tracking
    status: Mapped[str] = mapped_column(String(50), default="draft")  # draft | edited | copied | sent
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True
    )  # for re-drafts / follow-ups

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    person: Mapped["Person"] = relationship()  # noqa: F821
