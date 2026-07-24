import uuid
from datetime import datetime

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WaitlistSignup(Base):
    """A pre-launch waitlist entry captured from the public landing page.

    This table is intentionally *not* user-scoped: entries are submitted by
    prospective users who have no account yet. RLS is enabled deny-all in the
    creating migration so the anon/authenticated Supabase roles cannot read it;
    only the backend (postgres owner) and the token-gated admin export endpoint
    can access rows.

    It also backs the pre-launch **referral loop**: each signup gets a public,
    shareable ``referral_code`` (surfaced in ``?ref=`` links) and a *secret*
    ``access_token_hash`` (the owner-only key for their referral dashboard and
    the one-click email-verification link). A referral only *counts* once the
    invited person verifies their email — ``verified_referral_count`` is the
    denormalized tally of verified invitees and the sort key for queue position.
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

    # --- Goals ------------------------------------------------------------
    # Selected goal keys from the signup form's chips (see
    # ``app.utils.waitlist_goals.WAITLIST_GOAL_KEYS``). The free-text detail
    # reuses ``note`` above rather than adding a redundant column.
    goals: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # --- Optional resume --------------------------------------------------
    # The original file lives in Supabase Storage; only its object path and
    # metadata are stored here. Parsing happens asynchronously in the Celery
    # worker (never inline — the sandboxed parser can use 512 MiB, which would
    # be an OOM surface on the public endpoint's web service).
    resume_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    resume_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resume_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # none | pending | ready | failed
    resume_parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none"
    )
    # Deferred: the extracted text can be ~1 MB, and these are never needed by
    # the hot referral-status / admin-export reads (cf. defer(Job.description)).
    resume_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, deferred=True
    )
    resume_parsed: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, deferred=True
    )

    # --- Referral loop ---------------------------------------------------
    # PUBLIC, shareable code (appears in the referrer's ?ref= link). Minted at
    # signup; backfilled for pre-referral rows by migration 061.
    referral_code: Mapped[str] = mapped_column(
        String(16), nullable=False, unique=True, index=True
    )
    # Who referred this signup (self-FK). NULL for organic signups.
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("waitlist_signups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Double-opt-in gate: a referral only counts once the invitee verifies.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Denormalized count of *verified* invitees; also the queue-position sort key.
    verified_referral_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # SECRET owner key (SHA-256 of an ``nrw_`` token, plaintext returned once).
    # Authenticates the referral dashboard + the verification link. NULL for
    # grandfathered pre-referral rows (they never received a link).
    access_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    # Peer IP at signup — for per-IP anti-fraud caps only.
    signup_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
