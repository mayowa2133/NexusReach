"""Add goals + optional resume columns to waitlist_signups.

Revision ID: 062_add_waitlist_goals_resume
Revises: 061_add_referrals

The pre-launch waitlist now asks what the person wants to achieve on Solomon
(multi-select goal chips, with the free-text detail reusing the existing
``note`` column) and accepts an optional resume upload.

The resume file itself is stored in Supabase Storage — only its object path and
metadata land here. ``resume_text`` / ``resume_parsed`` are filled in
asynchronously by ``app.tasks.waitlist_resume.parse_waitlist_resume``; the
sandboxed parser can use 512 MiB, so it never runs inline on the public
endpoint's web service.

This ALTERs an existing table that already has RLS enabled (migration 057), so
per the project's RLS rule **no new ENABLE ROW LEVEL SECURITY is needed** (that
rule covers newly *created* tables).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "062_add_waitlist_goals_resume"
down_revision = "061_add_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Goals: array of goal keys selected from the signup form's chips.
    op.add_column("waitlist_signups", sa.Column("goals", JSONB, nullable=True))

    # Optional resume — file in Supabase Storage, metadata + parse output here.
    op.add_column(
        "waitlist_signups", sa.Column("resume_path", sa.String(500), nullable=True)
    )
    op.add_column(
        "waitlist_signups", sa.Column("resume_filename", sa.String(300), nullable=True)
    )
    op.add_column(
        "waitlist_signups",
        sa.Column("resume_content_type", sa.String(120), nullable=True),
    )
    op.add_column(
        "waitlist_signups", sa.Column("resume_size_bytes", sa.Integer, nullable=True)
    )
    op.add_column(
        "waitlist_signups",
        sa.Column("resume_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "waitlist_signups",
        sa.Column(
            "resume_parse_status",
            sa.String(16),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column("waitlist_signups", sa.Column("resume_text", sa.Text, nullable=True))
    op.add_column("waitlist_signups", sa.Column("resume_parsed", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("waitlist_signups", "resume_parsed")
    op.drop_column("waitlist_signups", "resume_text")
    op.drop_column("waitlist_signups", "resume_parse_status")
    op.drop_column("waitlist_signups", "resume_uploaded_at")
    op.drop_column("waitlist_signups", "resume_size_bytes")
    op.drop_column("waitlist_signups", "resume_content_type")
    op.drop_column("waitlist_signups", "resume_filename")
    op.drop_column("waitlist_signups", "resume_path")
    op.drop_column("waitlist_signups", "goals")
