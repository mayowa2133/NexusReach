"""One durable, coalesced rescoring request per account."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProfileRescoreRequest(Base):
    __tablename__ = "profile_rescore_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    requested_version: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ticket: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
