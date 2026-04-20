import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InterviewPrepBrief(Base):
    """Interview-prep artifact tied to a single (user, job).

    Honest by construction: generated content is deterministic from job +
    story-bank inputs and labelled inferred vs sourced. `user_notes` is the
    human editable layer. Rounds themselves continue to live on `jobs.interview_rounds`.
    """

    __tablename__ = "interview_prep_briefs"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_interview_prep_user_job"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )

    company_overview: Mapped[str | None] = mapped_column(Text)
    role_summary: Mapped[str | None] = mapped_column(Text)

    likely_rounds: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    question_categories: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    prep_themes: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    story_map: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    sourced_signals: Mapped[dict | None] = mapped_column(JSONB)

    user_notes: Mapped[str | None] = mapped_column(Text)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
