import uuid
from datetime import date, datetime

from sqlalchemy import Date, String, Boolean, Text, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    # Core fields
    external_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_logo: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(255))
    locations: Mapped[list[dict] | None] = mapped_column(JSONB)
    country_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    countries: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    location_lat: Mapped[float | None] = mapped_column(Float)
    location_lng: Mapped[float | None] = mapped_column(Float)
    location_radius_km: Mapped[float | None] = mapped_column(Float)
    location_geocode_label: Mapped[str | None] = mapped_column(String(255))
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    work_mode: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    employment_type: Mapped[str | None] = mapped_column(String(50))
    experience_level: Mapped[str | None] = mapped_column(String(50))  # noqa: F821
    # intern | new_grad | mid | senior
    experience_level_confidence: Mapped[float | None] = mapped_column(Float)

    # Salary
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    salary_period: Mapped[str | None] = mapped_column(String(50))

    # Source tracking
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    ats: Mapped[str | None] = mapped_column(String(50))
    ats_slug: Mapped[str | None] = mapped_column(String(255))
    posted_at: Mapped[str | None] = mapped_column(String(50))
    # Calendar-validated parse of posted_at (NULL when unparseable/invalid).
    # Used for crash-proof, indexed date ordering (audit pass-2 P3).
    posted_date: Mapped[date | None] = mapped_column(Date, index=True)
    # Precise posting timestamp — set ONLY when the source gives genuine sub-day
    # precision (ISO datetime, epoch, "30 minutes ago"), so the UI can show
    # "15 minutes ago" honestly. NULL for date-only / coarse sources, which fall
    # back to posted_date (day granularity). Primary key for recency ordering.
    posted_ts: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    source_status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active"
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    not_seen_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # People pre-warm gate: newly discovered jobs are queued for a background
    # people search and held out of the feed until that finishes (or a reveal
    # timeout elapses). "ready" = visible; "pending" = warming. Defaults to
    # "ready" so existing rows and non-discovery inserts are never hidden.
    people_prewarm_status: Mapped[str] = mapped_column(
        String(16), default="ready", server_default="ready", nullable=False
    )

    # Scoring
    match_score: Mapped[float | None] = mapped_column(Float)
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    scored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Dedup fingerprint
    fingerprint: Mapped[str | None] = mapped_column(String(255), index=True)
    # Canonical (query/fragment-stripped, ATS-resolved) URL for indexed dedup.
    # Lets URL dedup match with a single indexed lookup instead of scanning and
    # canonicalizing every job for the user+source in Python (audit H7).
    canonical_url: Mapped[str | None] = mapped_column(String(1000), index=True)

    # Kanban status
    stage: Mapped[str] = mapped_column(
        String(50), default="discovered"
    )
    # discovered | interested | researching | networking |
    # applied | interviewing | offer | accepted | rejected | withdrawn

    # Application tracking
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Interview rounds: [{round, type, scheduled_at, completed, interviewer, notes}]
    # Stored as a JSON array of round dicts; annotated as list|dict for the
    # rare legacy dict-shaped value (audit L1).
    interview_rounds: Mapped[list | dict | None] = mapped_column(JSONB)
    # Offer details: {salary, equity, bonus, deadline, status, notes}
    offer_details: Mapped[dict | None] = mapped_column(JSONB)

    # Tags / metadata
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    metadata_provenance: Mapped[dict | None] = mapped_column(JSONB)
    department: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)

    # Company research
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
