"""Durable account/global reservations for externally billed operations."""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaidBudgetBucket(Base):
    __tablename__ = "paid_budget_buckets"
    __table_args__ = (
        UniqueConstraint("scope", "period", name="uq_paid_budget_scope_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scope: Mapped[str] = mapped_column(String(80))
    period: Mapped[date] = mapped_column(Date)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    calls_settled: Mapped[int] = mapped_column(Integer, default=0)
    calls_reserved: Mapped[int] = mapped_column(Integer, default=0)
    tokens_settled: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reserved: Mapped[int] = mapped_column(Integer, default=0)
    active_operations: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaidReservation(Base):
    __tablename__ = "paid_reservations"

    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    service: Mapped[str] = mapped_column(String(60))
    period: Mapped[date] = mapped_column(Date)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    actual_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
