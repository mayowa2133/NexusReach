"""Add provider tracking columns to outreach_logs for post-send reconciliation.

Revision ID: 030_add_outreach_provider_tracking
Revises: 029_add_search_preference_mode
"""

from alembic import op
import sqlalchemy as sa


revision = "030_add_outreach_provider_tracking"
down_revision = "029_add_search_preference_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_logs",
        sa.Column("provider", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "outreach_logs",
        sa.Column("provider_draft_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "outreach_logs",
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "outreach_logs",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_logs", "sent_at")
    op.drop_column("outreach_logs", "provider_message_id")
    op.drop_column("outreach_logs", "provider_draft_id")
    op.drop_column("outreach_logs", "provider")
