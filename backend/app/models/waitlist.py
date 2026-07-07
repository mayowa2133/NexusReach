import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WaitlistSignup(Base):
    """A pre-launch waitlist entry captured from the public landing page.

    This table is intentionally *not* user-scoped: entries are submitted by
    prospective users who have no account yet. RLS is enabled deny-all in the
    creating migration so the anon/authenticated Supabase roles cannot read it;
    only the backend (postgres owner) and the token-gated admin export endpoint
    can access rows.
    """

    __tablename__ = "waitlist_signups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Lowercased, trimmed email — unique so a repeat submission upserts.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # What they do today (current title / headline). NB: not "current_role" —
    # that is a reserved SQL keyword and a footgun in any raw query.
    current_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # What they're looking for (target role / focus).
    target_role: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Free-form "anything else" / how they heard about us.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which CTA / page section the submission came from (analytics).
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Whether the launch invite has been sent (owner flips this at launch).
    invited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
