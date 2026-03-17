"""add starred to jobs

Revision ID: 003_add_starred_to_jobs
Revises: 002_add_relevance_score
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "003_add_starred_to_jobs"
down_revision = "002_add_relevance_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("starred", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("jobs", "starred")
