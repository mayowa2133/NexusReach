import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CompanionToken(Base):
    """Long-lived, revocable bearer token for the browser companion extension.

    Replaces storing the user's short-lived Supabase JWT in extension storage
    (that JWT expires within the hour, silently disconnecting the companion).
    Only the SHA-256 hash is persisted — the ``nrc_``-prefixed plaintext is
    returned exactly once at mint time. Accepted only by endpoints that opt
    into ``get_companion_or_user_id``; never a general-purpose credential.
    Minting revokes all previously active tokens (one active per user).
    """

    __tablename__ = "companion_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 hex digest of the plaintext token — the plaintext is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Diagnostic freshness signal, written at most once per hour on use.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
