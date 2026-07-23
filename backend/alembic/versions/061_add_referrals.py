"""Add referral-loop columns to waitlist_signups.

Revision ID: 061_add_referrals
Revises: 060_add_companion_tokens

Turns the flat pre-launch waitlist into a referral loop. New columns on
``waitlist_signups``:

- ``referral_code``      — PUBLIC shareable code (appears in ?ref= links)
- ``referred_by_id``     — self-FK to the referrer (NULL for organic signups)
- ``email_verified`` / ``verified_at`` — double-opt-in gate
- ``verified_referral_count`` — denormalized tally + queue-position sort key
- ``access_token_hash``  — SECRET owner key (dashboard + verification link)
- ``signup_ip``          — peer IP, anti-fraud caps only

This ALTERs an existing table that already has RLS enabled (migration 057), so
per the project's RLS rule **no new ENABLE ROW LEVEL SECURITY is needed** (the
rule covers newly *created* tables).

Existing rows are grandfathered: each gets a freshly-minted ``referral_code``
and ``email_verified = true`` — they joined before verification existed, so they
still count toward the verified launch total.
"""

import secrets

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "061_add_referrals"
down_revision = "060_add_companion_tokens"
branch_labels = None
depends_on = None

# Unambiguous base32-ish alphabet (no I/L/O/0/1) for human-shareable codes.
# Kept in sync with app.services.referral_service._CODE_ALPHABET; duplicated here
# because migrations must stay self-contained and not import mutable app code.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 10


def _gen_code(seen: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
        if code not in seen:
            seen.add(code)
            return code


def upgrade() -> None:
    op.add_column(
        "waitlist_signups",
        sa.Column("referral_code", sa.String(16), nullable=True),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column(
            "referred_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("waitlist_signups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column(
            "email_verified",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column(
            "verified_referral_count",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column("access_token_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column("signup_ip", sa.String(64), nullable=True),
    )

    # Backfill existing rows: mint a referral_code each, grandfather verified.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM waitlist_signups")).fetchall()
    seen: set[str] = set()
    for (row_id,) in rows:
        bind.execute(
            sa.text(
                "UPDATE waitlist_signups "
                "SET referral_code = :code, email_verified = true "
                "WHERE id = :id"
            ),
            {"code": _gen_code(seen), "id": row_id},
        )

    # Every row now has a code — enforce NOT NULL + uniqueness.
    op.alter_column("waitlist_signups", "referral_code", nullable=False)
    op.create_index(
        "ix_waitlist_signups_referral_code",
        "waitlist_signups",
        ["referral_code"],
        unique=True,
    )
    op.create_index(
        "ix_waitlist_signups_referred_by_id",
        "waitlist_signups",
        ["referred_by_id"],
    )
    op.create_index(
        "ix_waitlist_signups_access_token_hash",
        "waitlist_signups",
        ["access_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_waitlist_signups_access_token_hash", table_name="waitlist_signups"
    )
    op.drop_index(
        "ix_waitlist_signups_referred_by_id", table_name="waitlist_signups"
    )
    op.drop_index(
        "ix_waitlist_signups_referral_code", table_name="waitlist_signups"
    )
    op.drop_column("waitlist_signups", "signup_ip")
    op.drop_column("waitlist_signups", "access_token_hash")
    op.drop_column("waitlist_signups", "verified_referral_count")
    op.drop_column("waitlist_signups", "verified_at")
    op.drop_column("waitlist_signups", "email_verified")
    op.drop_column("waitlist_signups", "referred_by_id")
    op.drop_column("waitlist_signups", "referral_code")
