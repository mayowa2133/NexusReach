"""Add waitlist_signups table for pre-launch waitlist capture.

Revision ID: 057_add_waitlist_signups
Revises: 056_add_jobs_performance_indexes

Stores pre-launch waitlist entries submitted from the public landing page
(name, email, LinkedIn, current/target role, note). The table is NOT
user-scoped — submitters have no account yet.

Per the project's RLS rule (any new public table must enable RLS in the same
migration that creates it — migration 055 does not cover tables added later),
we ``ENABLE ROW LEVEL SECURITY`` with no policies so the anon/authenticated
Supabase roles get deny-all. The backend connects as the ``postgres`` owner and
bypasses RLS (we ENABLE, never FORCE), so the FastAPI endpoints are unaffected.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "057_add_waitlist_signups"
down_revision = "056_add_jobs_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waitlist_signups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        # "current_title" not "current_role" — the latter is a reserved SQL keyword.
        sa.Column("current_title", sa.String(300), nullable=True),
        sa.Column("target_role", sa.String(300), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column(
            "invited",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_waitlist_signups_email",
        "waitlist_signups",
        ["email"],
        unique=True,
    )
    # New public table => enable RLS deny-all (see module docstring / truth on RLS).
    op.execute("ALTER TABLE waitlist_signups ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_waitlist_signups_email", table_name="waitlist_signups")
    op.drop_table("waitlist_signups")
