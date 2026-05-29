"""Add normalized job metadata quality fields.

Revision ID: 042_add_job_metadata_quality_fields
Revises: 041_clear_plaintext_oauth_tokens
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "042_add_job_metadata_quality_fields"
down_revision = "041_clear_plaintext_oauth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("locations", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("jobs", sa.Column("country_codes", postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column("jobs", sa.Column("countries", postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column("jobs", sa.Column("work_mode", sa.String(length=50), nullable=True))
    op.add_column("jobs", sa.Column("salary_period", sa.String(length=50), nullable=True))
    op.add_column("jobs", sa.Column("experience_level_confidence", sa.Float(), nullable=True))
    op.add_column("jobs", sa.Column("metadata_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index("ix_jobs_country_codes", "jobs", ["country_codes"], postgresql_using="gin")
    op.create_index("ix_jobs_countries", "jobs", ["countries"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_jobs_countries", table_name="jobs")
    op.drop_index("ix_jobs_country_codes", table_name="jobs")
    op.drop_column("jobs", "metadata_provenance")
    op.drop_column("jobs", "experience_level_confidence")
    op.drop_column("jobs", "salary_period")
    op.drop_column("jobs", "work_mode")
    op.drop_column("jobs", "countries")
    op.drop_column("jobs", "country_codes")
    op.drop_column("jobs", "locations")
