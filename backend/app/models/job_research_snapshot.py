import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobResearchSnapshot(Base):
    """Persisted people-search artifact for a single job.

    One row per (user, job) — replaced on each fresh search. Lets the job
    command center recover the latest live recruiter / hiring manager / peer
    targeting across sessions without re-running the search providers.
    """

    __tablename__ = "job_research_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )

    company_name: Mapped[str | None] = mapped_column(String(255))
    target_count_per_bucket: Mapped[int | None] = mapped_column(Integer)

    recruiters: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    hiring_managers: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    peers: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821
    your_connections: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821

    recruiter_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manager_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    peer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warm_path_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    errors: Mapped[list | None] = mapped_column(JSONB)  # noqa: F821

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
