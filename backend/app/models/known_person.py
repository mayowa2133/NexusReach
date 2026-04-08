"""Global known people models — shared discovery cache across all users.

These tables store people discovered through PUBLIC sources only (Apollo,
SearXNG, The Org, hiring team search, GitHub, etc.).  User-imported
LinkedIn connection data must NEVER enter these tables.

Every time any user's people search discovers someone from a public source,
the result is written through to KnownPerson.  Subsequent searches by
other users check this cache first, getting instant results without
burning API calls.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class KnownPerson(Base):
    __tablename__ = "known_persons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Identity
    full_name: Mapped[str | None] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(255))
    seniority: Mapped[str | None] = mapped_column(String(100))

    # Public profile links
    linkedin_url: Mapped[str | None] = mapped_column(String(500), unique=True)
    github_url: Mapped[str | None] = mapped_column(String(500))

    # Contact (only from public sources like Apollo/Hunter)
    work_email: Mapped[str | None] = mapped_column(String(255))

    # External IDs
    apollo_id: Mapped[str | None] = mapped_column(String(100), unique=True)

    # Enrichment data
    profile_data: Mapped[dict | None] = mapped_column(JSONB)
    github_data: Mapped[dict | None] = mapped_column(JSONB)

    # Source tracking — only public discovery sources allowed
    primary_source: Mapped[str] = mapped_column(String(50), nullable=False)
    all_sources: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    # Discovery metrics
    discovery_count: Mapped[int] = mapped_column(Integer, default=1)
    last_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Staleness tracking
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    verification_status: Mapped[str | None] = mapped_column(
        String(50), default="fresh"
    )  # fresh | stale | reverified | expired

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    companies: Mapped[list["KnownPersonCompany"]] = relationship(  # noqa: F821
        back_populates="known_person", cascade="all, delete-orphan"
    )


class KnownPersonCompany(Base):
    __tablename__ = "known_person_companies"

    __table_args__ = (
        UniqueConstraint(
            "known_person_id", "normalized_company_name",
            name="uq_known_person_company",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    known_person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("known_persons.id", ondelete="CASCADE"),
    )

    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_company_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    company_domain: Mapped[str | None] = mapped_column(String(255))
    title_at_company: Mapped[str | None] = mapped_column(String(255))

    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str | None] = mapped_column(String(50))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    known_person: Mapped["KnownPerson"] = relationship(back_populates="companies")
