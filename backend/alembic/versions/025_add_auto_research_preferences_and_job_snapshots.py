"""Add auto research preferences and job research snapshot columns.

Revision ID: 025_add_auto_research_preferences_and_job_snapshots
Revises: 024_add_job_apply_url
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "025_add_auto_research_preferences_and_job_snapshots"
down_revision = "024_add_job_apply_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_auto_research_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_company_name", sa.String(length=255), nullable=False),
        sa.Column("auto_find_people", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_find_emails", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.UniqueConstraint(
            "user_id",
            "normalized_company_name",
            name="uq_company_auto_research_user_company",
        ),
    )
    op.create_index(
        "ix_company_auto_research_preferences_normalized_company_name",
        "company_auto_research_preferences",
        ["normalized_company_name"],
    )
    op.create_index(
        "ix_company_auto_research_preferences_user_id",
        "company_auto_research_preferences",
        ["user_id"],
    )

    op.add_column("jobs", sa.Column("auto_research_status", sa.String(length=50), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("auto_research_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("auto_research_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("jobs", sa.Column("auto_research_error", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("auto_research_snapshot", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "auto_research_snapshot")
    op.drop_column("jobs", "auto_research_error")
    op.drop_column("jobs", "auto_research_completed_at")
    op.drop_column("jobs", "auto_research_requested_at")
    op.drop_column("jobs", "auto_research_status")

    op.drop_index(
        "ix_company_auto_research_preferences_user_id",
        table_name="company_auto_research_preferences",
    )
    op.drop_index(
        "ix_company_auto_research_preferences_normalized_company_name",
        table_name="company_auto_research_preferences",
    )
    op.drop_table("company_auto_research_preferences")
