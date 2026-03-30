"""Add refresh metadata columns to search_preferences.

Revision ID: 017
Revises: 016
"""

from alembic import op
import sqlalchemy as sa


revision = "017_add_search_preference_refresh_metadata"
down_revision = "016_add_search_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_preferences",
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "search_preferences",
        sa.Column("new_jobs_found", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "new_jobs_found")
    op.drop_column("search_preferences", "last_refreshed_at")
