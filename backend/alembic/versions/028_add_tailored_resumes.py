"""Add tailored_resumes table.

Revision ID: 028_add_tailored_resumes
Revises: 027_add_job_scored_at
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "028_add_tailored_resumes"
down_revision = "027_add_job_scored_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tailored_resumes",
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
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("skills_to_emphasize", JSONB, nullable=True),
        sa.Column("skills_to_add", JSONB, nullable=True),
        sa.Column("keywords_to_add", JSONB, nullable=True),
        sa.Column("bullet_rewrites", JSONB, nullable=True),
        sa.Column("section_suggestions", JSONB, nullable=True),
        sa.Column("overall_strategy", sa.Text, nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_tailored_resumes_user_job",
        "tailored_resumes",
        ["user_id", "job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tailored_resumes_user_job")
    op.drop_table("tailored_resumes")
