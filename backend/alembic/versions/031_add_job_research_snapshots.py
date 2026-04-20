"""Add job_research_snapshots table.

Revision ID: 031_add_job_research_snapshots
Revises: 030_add_outreach_provider_tracking
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "031_add_job_research_snapshots"
down_revision = "030_add_outreach_provider_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_research_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("target_count_per_bucket", sa.Integer, nullable=True),
        sa.Column("recruiters", JSONB, nullable=True),
        sa.Column("hiring_managers", JSONB, nullable=True),
        sa.Column("peers", JSONB, nullable=True),
        sa.Column("your_connections", JSONB, nullable=True),
        sa.Column("recruiter_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("manager_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("peer_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("warm_path_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("verified_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_candidates", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", JSONB, nullable=True),
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
        "ix_job_research_snapshots_user_job",
        "job_research_snapshots",
        ["user_id", "job_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_job_research_snapshots_user_job")
    op.drop_table("job_research_snapshots")
