"""Add experience_level column to jobs table."""

from alembic import op
import sqlalchemy as sa


revision = "018_add_job_experience_level"
down_revision = "017_add_search_preference_refresh_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("experience_level", sa.String(50), nullable=True))
    op.create_index("ix_jobs_experience_level", "jobs", ["experience_level"])


def downgrade() -> None:
    op.drop_index("ix_jobs_experience_level", table_name="jobs")
    op.drop_column("jobs", "experience_level")
