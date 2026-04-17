import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SearchPreference(Base):
    __tablename__ = "search_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    # Search criteria (mirrors JobSearchRequest)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False)

    # Whether this preference is active for auto-refresh
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Discover mode this preference was saved from.
    # "default" = standard job boards / ATS. "startup" = startup discover flow
    # (YC, Wellfound, VentureLoop, ecosystem sources).
    mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="default", server_default="default"
    )

    # Auto-refresh metadata
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_jobs_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
