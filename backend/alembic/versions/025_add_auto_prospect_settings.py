"""Add auto_prospect settings columns.

Revision ID: 025
Revises: 024
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "025_add_auto_prospect_settings"
down_revision = "024_add_job_apply_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("auto_prospect_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "user_settings",
        sa.Column("auto_prospect_company_names", JSONB(), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column("auto_draft_on_apply", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "auto_draft_on_apply")
    op.drop_column("user_settings", "auto_prospect_company_names")
    op.drop_column("user_settings", "auto_prospect_enabled")
