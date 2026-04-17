"""Add mode column to search_preferences for startup-aware refresh.

Revision ID: 029_add_search_preference_mode
Revises: 028_add_tailored_resumes
"""

from alembic import op
import sqlalchemy as sa


revision = "029_add_search_preference_mode"
down_revision = "028_add_tailored_resumes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_preferences",
        sa.Column(
            "mode",
            sa.String(length=32),
            nullable=False,
            server_default="default",
        ),
    )


def downgrade() -> None:
    op.drop_column("search_preferences", "mode")
