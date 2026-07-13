"""Version tailored resumes by resume, job, prompt, and rubric inputs.

Revision ID: 059_version_tailored_resumes
Revises: 058_add_job_preferences
"""

from alembic import op
import sqlalchemy as sa


revision = "059_version_tailored_resumes"
down_revision = "058_add_job_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tailored_resumes", sa.Column("input_hash", sa.String(64)))
    op.add_column("tailored_resumes", sa.Column("prompt_version", sa.String(64)))
    op.add_column("tailored_resumes", sa.Column("rubric_version", sa.String(64)))
    op.create_index(
        "ix_tailored_resumes_input_hash",
        "tailored_resumes",
        ["input_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_tailored_resumes_input_hash", table_name="tailored_resumes")
    op.drop_column("tailored_resumes", "rubric_version")
    op.drop_column("tailored_resumes", "prompt_version")
    op.drop_column("tailored_resumes", "input_hash")
