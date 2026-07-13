"""Add companion_tokens for the browser extension's long-lived auth.

Revision ID: 060_add_companion_tokens
Revises: 059_version_tailored_resumes

The companion extension previously stored the user's Supabase access JWT,
which expires within the hour and silently disconnected the extension. This
table backs ``nrc_``-prefixed long-lived tokens: hashed at rest (SHA-256),
expiring, revocable, one active per user.

Per the project's RLS rule (any new public table must enable RLS in the same
migration that creates it — migration 055 does not cover tables added later),
we ``ENABLE ROW LEVEL SECURITY`` with no policies so the anon/authenticated
Supabase roles get deny-all. The backend connects as the ``postgres`` owner
and bypasses RLS (we ENABLE, never FORCE).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "060_add_companion_tokens"
down_revision = "059_version_tailored_resumes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companion_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_companion_tokens_user_id", "companion_tokens", ["user_id"]
    )
    op.create_index(
        "ix_companion_tokens_token_hash",
        "companion_tokens",
        ["token_hash"],
        unique=True,
    )
    # New public table => enable RLS deny-all (see module docstring).
    op.execute("ALTER TABLE companion_tokens ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_companion_tokens_token_hash", table_name="companion_tokens")
    op.drop_index("ix_companion_tokens_user_id", table_name="companion_tokens")
    op.drop_table("companion_tokens")
