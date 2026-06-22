"""Add precise posting timestamp for accurate freshness + recency ordering.

Revision ID: 053_add_job_posted_ts
Revises: 052_add_job_people_prewarm_status

``posted_ts`` holds the exact posting time when a source provides sub-day
precision (ISO datetime, epoch, "30 minutes ago"), so the board can show
"15 minutes ago" honestly and order by real posting time instead of falling
back to our ingest time. NULL for date-only sources, which keep using the
day-granularity ``posted_date``. No backfill: existing rows order by
``coalesce(posted_ts, posted_date, created_at)`` and show day-level dates as
before; new ingests populate ``posted_ts`` where the source allows.
"""

from alembic import op
import sqlalchemy as sa


revision = "053_add_job_posted_ts"
down_revision = "052_add_job_people_prewarm_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("posted_ts", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_posted_ts", "jobs", ["posted_ts"])


def downgrade() -> None:
    op.drop_index("ix_jobs_posted_ts", table_name="jobs")
    op.drop_column("jobs", "posted_ts")
