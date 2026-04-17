"""Add auto_prospect settings columns.

Revision ID: 025
Revises: 025_add_auto_research_preferences_and_job_snapshots
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "025_add_auto_prospect_settings"
down_revision = "025_add_auto_research_preferences_and_job_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_columns = {
        column["name"]
        for column in inspector.get_columns("user_settings")
    }

    if "auto_prospect_enabled" not in existing_columns:
        op.add_column(
            "user_settings",
            sa.Column("auto_prospect_enabled", sa.Boolean(), server_default="false", nullable=False),
        )
    if "auto_prospect_company_names" not in existing_columns:
        op.add_column(
            "user_settings",
            sa.Column("auto_prospect_company_names", JSONB(), nullable=True),
        )
    if "auto_draft_on_apply" not in existing_columns:
        op.add_column(
            "user_settings",
            sa.Column("auto_draft_on_apply", sa.Boolean(), server_default="false", nullable=False),
        )


def downgrade() -> None:
    op.drop_column("user_settings", "auto_draft_on_apply")
    op.drop_column("user_settings", "auto_prospect_company_names")
    op.drop_column("user_settings", "auto_prospect_enabled")
