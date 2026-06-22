"""Add per-job people pre-warm visibility gate.

Revision ID: 052_add_job_people_prewarm_status
Revises: 051_add_people_prewarm

Newly discovered jobs are queued for a background people search and held out
of the feed until it finishes (or a reveal timeout elapses), so opening a job
shows its contacts instantly. "ready" = visible, "pending" = warming. Existing
rows default to "ready" so nothing already in the feed disappears.
"""

from alembic import op
import sqlalchemy as sa


revision = "052_add_job_people_prewarm_status"
down_revision = "051_add_people_prewarm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "people_prewarm_status",
            sa.String(length=16),
            nullable=False,
            server_default="ready",
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "people_prewarm_status")
