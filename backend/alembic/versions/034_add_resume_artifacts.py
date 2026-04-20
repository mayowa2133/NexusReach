"""Add resume_artifacts table.

Revision ID: 034_add_resume_artifacts
Revises: 033_add_interview_prep_briefs
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "034_add_resume_artifacts"
down_revision = "033_add_interview_prep_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resume_artifacts",
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
        sa.Column(
            "tailored_resume_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tailored_resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("format", sa.String(length=50), nullable=False, server_default="markdown"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("user_id", "job_id", name="uq_resume_artifacts_user_job"),
    )
    op.create_index("ix_resume_artifacts_user_id", "resume_artifacts", ["user_id"])
    op.create_index("ix_resume_artifacts_job_id", "resume_artifacts", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_artifacts_job_id")
    op.drop_index("ix_resume_artifacts_user_id")
    op.drop_table("resume_artifacts")
