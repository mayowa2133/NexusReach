"""Add search_logs table for discovery audit trail.

Revision ID: 016_add_search_logs
Revises: 015_add_company_public_identity_hints
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "016_add_search_logs"
down_revision = "015_add_company_public_identity_hints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("search_type", sa.String(50), nullable=False),
        sa.Column("recruiter_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("manager_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("peer_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("errors", postgresql.JSONB, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("search_logs")
