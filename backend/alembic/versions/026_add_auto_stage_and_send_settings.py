"""Add auto_stage_on_apply, auto_send settings, and scheduled_send_at.

Revision ID: 026
Revises: 025
"""

from alembic import op
import sqlalchemy as sa

revision = "026_add_auto_stage_and_send_settings"
down_revision = "025_add_auto_prospect_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("auto_stage_on_apply", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "user_settings",
        sa.Column("auto_send_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "user_settings",
        sa.Column("auto_send_delay_minutes", sa.Integer(), server_default="30", nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("scheduled_send_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "scheduled_send_at")
    op.drop_column("user_settings", "auto_send_delay_minutes")
    op.drop_column("user_settings", "auto_send_enabled")
    op.drop_column("user_settings", "auto_stage_on_apply")
