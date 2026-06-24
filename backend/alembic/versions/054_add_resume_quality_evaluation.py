"""Add persisted resume quality-gate results.

Revision ID: 054_add_resume_quality_evaluation
Revises: 053_add_job_posted_ts
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "054_add_resume_quality_evaluation"
down_revision = "053_add_job_posted_ts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resume_artifacts",
        sa.Column("quality_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "resume_artifacts",
        sa.Column("quality_evaluation", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("resume_artifacts", "quality_evaluation")
    op.drop_column("resume_artifacts", "quality_score")
