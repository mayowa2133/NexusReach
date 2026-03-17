"""Add smtp_domain_results table for SMTP probe tracking and blocklist.

Revision ID: 007_add_smtp_domain_results
Revises: 006_add_search_preferences
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision = "007_add_smtp_domain_results"
down_revision = "006_add_search_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smtp_domain_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("domain", sa.String(255), nullable=False, unique=True),
        sa.Column("success_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("catch_all_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("greylist_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_smtp_domain_results_domain", "smtp_domain_results", ["domain"])
    op.create_index(
        "ix_smtp_domain_results_blocked_until",
        "smtp_domain_results",
        ["blocked_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_smtp_domain_results_blocked_until")
    op.drop_index("ix_smtp_domain_results_domain")
    op.drop_table("smtp_domain_results")
