"""Add job refresh observability and source lifecycle fields.

Revision ID: 044_add_job_refresh_observability
Revises: 043_add_job_location_coordinates
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "044_add_job_refresh_observability"
down_revision = "043_add_job_location_coordinates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("source_status", sa.String(length=32), server_default="active", nullable=False),
    )
    op.add_column("jobs", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("not_seen_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute("UPDATE jobs SET last_seen_at = COALESCE(updated_at, created_at)")
    op.create_index("ix_jobs_source_status", "jobs", ["source_status"])
    op.create_index("ix_jobs_last_seen_at", "jobs", ["last_seen_at"])

    op.add_column(
        "search_preferences",
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "search_preferences",
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("search_preferences", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "search_preferences",
        sa.Column("last_duration_seconds", sa.Float(), nullable=True),
    )

    op.create_table(
        "job_refresh_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "search_preference_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("search_preferences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("remote_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_existing", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_job_refresh_runs_user_id", "job_refresh_runs", ["user_id"])
    op.create_index(
        "ix_job_refresh_runs_started_at", "job_refresh_runs", ["started_at"]
    )

    op.create_table(
        "job_source_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "refresh_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_refresh_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("existing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_job_source_runs_refresh_run_id", "job_source_runs", ["refresh_run_id"])
    op.create_index("ix_job_source_runs_source", "job_source_runs", ["source"])


def downgrade() -> None:
    op.drop_index("ix_job_source_runs_source", table_name="job_source_runs")
    op.drop_index("ix_job_source_runs_refresh_run_id", table_name="job_source_runs")
    op.drop_table("job_source_runs")

    op.drop_index("ix_job_refresh_runs_started_at", table_name="job_refresh_runs")
    op.drop_index("ix_job_refresh_runs_user_id", table_name="job_refresh_runs")
    op.drop_table("job_refresh_runs")

    op.drop_column("search_preferences", "last_duration_seconds")
    op.drop_column("search_preferences", "last_error")
    op.drop_column("search_preferences", "last_success_at")
    op.drop_column("search_preferences", "last_attempted_at")

    op.drop_index("ix_jobs_last_seen_at", table_name="jobs")
    op.drop_index("ix_jobs_source_status", table_name="jobs")
    op.drop_column("jobs", "not_seen_count")
    op.drop_column("jobs", "closed_at")
    op.drop_column("jobs", "last_seen_at")
    op.drop_column("jobs", "source_status")
