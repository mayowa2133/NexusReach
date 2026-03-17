"""Add starred column to companies table.

Revision ID: 004_add_starred_to_companies
Revises: 003_add_starred_to_jobs
"""

import sqlalchemy as sa
from alembic import op

revision = "004_add_starred_to_companies"
down_revision = "003_add_starred_to_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("starred", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("companies", "starred")
