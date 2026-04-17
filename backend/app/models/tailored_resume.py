import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TailoredResume(Base):
    __tablename__ = "tailored_resumes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )

    # LLM-generated tailoring output
    summary: Mapped[str | None] = mapped_column(Text)
    skills_to_emphasize: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    skills_to_add: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    keywords_to_add: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    bullet_rewrites: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    # [{original, rewritten, reason, experience_index}]
    section_suggestions: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    # [{section, suggestion}]
    overall_strategy: Mapped[str | None] = mapped_column(Text)

    # Metadata
    model: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
