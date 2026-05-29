"""Add normalized job location coordinates.

Revision ID: 043_add_job_location_coordinates
Revises: 042_add_job_metadata_quality_fields
"""

from alembic import op
import sqlalchemy as sa


revision = "043_add_job_location_coordinates"
down_revision = "042_add_job_metadata_quality_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("location_lat", sa.Float(), nullable=True))
    op.add_column("jobs", sa.Column("location_lng", sa.Float(), nullable=True))
    op.add_column("jobs", sa.Column("location_radius_km", sa.Float(), nullable=True))
    op.add_column("jobs", sa.Column("location_geocode_label", sa.String(length=255), nullable=True))
    op.create_index("ix_jobs_location_coords", "jobs", ["location_lat", "location_lng"])


def downgrade() -> None:
    op.drop_index("ix_jobs_location_coords", table_name="jobs")
    op.drop_column("jobs", "location_geocode_label")
    op.drop_column("jobs", "location_radius_km")
    op.drop_column("jobs", "location_lng")
    op.drop_column("jobs", "location_lat")
