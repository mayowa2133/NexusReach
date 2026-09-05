"""Referral campaign anti-replay ledger and scoped mailbox-proven credentials."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ReferralCampaign(Base):
    __tablename__ = 'referral_campaigns'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sealed_key: Mapped[str | None] = mapped_column(String(1000))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legacy_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReferralCredential(Base):
    __tablename__ = 'referral_credentials'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    signup_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('waitlist_signups.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferralCredit(Base):
    __tablename__ = 'referral_credits'
    __table_args__ = (UniqueConstraint('campaign_id', 'fingerprint', name='uq_referral_campaign_identity'),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[str] = mapped_column(String(64), ForeignKey('referral_campaigns.id'))
    fingerprint: Mapped[str] = mapped_column(String(64))
    referrer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('waitlist_signups.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notification_status: Mapped[str] = mapped_column(String(20), default='pending')
    notification_attempts: Mapped[int] = mapped_column(Integer, default=0)
    notification_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
