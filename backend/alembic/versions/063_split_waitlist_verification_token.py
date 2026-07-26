"""Give waitlist signups a dedicated, email-only verification token.

Revision ID: 063_split_waitlist_verification_token
Revises: 062_add_waitlist_goals_resume

Security fix. ``access_token_hash`` (migration 061) authenticated *both* the
referral dashboard and the one-click email-verification link, and the plaintext
token was returned in the ``POST /api/waitlist`` response. That made the
double-opt-in gate meaningless: whoever submitted the form was handed the
credential needed to verify the address, so a referrer could create and
self-verify unlimited fake invitees without ever touching a mailbox.

Verification now requires a separate ``nrv_`` token that is **only** ever
delivered by email and is consumed on first use (the column is set back to NULL
when the signup verifies). ``access_token_hash`` keeps its dashboard-read role.

Consequence: verification links already sent carry the old ``?t=`` access token
and stop working. Pre-launch volume is small and the plaintext of those tokens
cannot be recovered from their hashes, so there is nothing to backfill —
re-submitting the form issues a fresh verification email.

This ALTERs a table that already has RLS enabled (migration 057), so per the
project's RLS rule no new ENABLE ROW LEVEL SECURITY is needed (that rule covers
newly *created* tables).
"""

from alembic import op
import sqlalchemy as sa


revision = "063_split_waitlist_verification_token"
down_revision = "062_add_waitlist_goals_resume"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "waitlist_signups",
        sa.Column("verification_token_hash", sa.String(64), nullable=True),
    )
    # Unique: the token is a lookup key, and two signups must never share one.
    op.create_index(
        "ix_waitlist_signups_verification_token_hash",
        "waitlist_signups",
        ["verification_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_waitlist_signups_verification_token_hash",
        table_name="waitlist_signups",
    )
    op.drop_column("waitlist_signups", "verification_token_hash")
