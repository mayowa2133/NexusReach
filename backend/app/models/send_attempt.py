"""Durable evidence of a claimed external email side effect."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Index, text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SendAttempt(Base):
    __tablename__ = "send_attempts"
    __table_args__ = (Index("uq_unresolved_send_attempt", "message_id", unique=True,
        postgresql_where=text("outcome IN ('sending', 'delivery_unknown')")),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(30))
    payload_digest: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(30), default="sending")
    provider_reference: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
