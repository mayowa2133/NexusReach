"""Add interview_prep_briefs table.

Revision ID: 033_add_interview_prep_briefs
Revises: 032_add_stories
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "033_add_interview_prep_briefs"
down_revision = "032_add_stories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interview_prep_briefs",
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
        sa.Column("company_overview", sa.Text, nullable=True),
        sa.Column("role_summary", sa.Text, nullable=True),
        sa.Column("likely_rounds", JSONB, nullable=True),
        sa.Column("question_categories", JSONB, nullable=True),
        sa.Column("prep_themes", JSONB, nullable=True),
        sa.Column("story_map", JSONB, nullable=True),
        sa.Column("sourced_signals", JSONB, nullable=True),
        sa.Column("user_notes", sa.Text, nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
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
        sa.UniqueConstraint("user_id", "job_id", name="uq_interview_prep_user_job"),
    )
    op.create_index(
        "ix_interview_prep_briefs_user_id", "interview_prep_briefs", ["user_id"]
    )
    op.create_index(
        "ix_interview_prep_briefs_job_id", "interview_prep_briefs", ["job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_interview_prep_briefs_job_id")
    op.drop_index("ix_interview_prep_briefs_user_id")
    op.drop_table("interview_prep_briefs")
