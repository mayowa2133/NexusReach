"""Add apply_url column to jobs table.

Revision ID: 024
Revises: 023
"""

from alembic import op
import sqlalchemy as sa

revision = "024_add_job_apply_url"
down_revision = "023_add_known_persons_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("apply_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "apply_url")
