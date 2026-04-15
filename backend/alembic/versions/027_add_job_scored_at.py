"""Add scored_at column to jobs for incremental re-scoring.

Revision ID: 027
Revises: 026
"""

from alembic import op
import sqlalchemy as sa

revision = "027_add_job_scored_at"
down_revision = "026_add_auto_stage_and_send_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "scored_at")
