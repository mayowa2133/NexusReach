"""add cadence digest settings to user_settings

Revision ID: 037_add_cadence_digest
Revises: 036_add_cadence_settings
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "037_add_cadence_digest"
down_revision = "036_add_cadence_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("cadence_digest_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "user_settings",
        sa.Column("cadence_digest_last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "cadence_digest_last_sent_at")
    op.drop_column("user_settings", "cadence_digest_enabled")
