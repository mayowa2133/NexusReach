"""add cadence threshold settings to user_settings

Revision ID: 036_add_cadence_settings
Revises: 035_add_resume_review_fields
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "036_add_cadence_settings"
down_revision = "035_add_resume_review_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("draft_unsent_threshold_hours", sa.Integer(), nullable=False, server_default="24"))
    op.add_column("user_settings", sa.Column("awaiting_reply_threshold_days", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("user_settings", sa.Column("applied_untouched_threshold_days", sa.Integer(), nullable=False, server_default="7"))
    op.add_column("user_settings", sa.Column("thank_you_window_hours", sa.Integer(), nullable=False, server_default="48"))


def downgrade() -> None:
    op.drop_column("user_settings", "thank_you_window_hours")
    op.drop_column("user_settings", "applied_untouched_threshold_days")
    op.drop_column("user_settings", "awaiting_reply_threshold_days")
    op.drop_column("user_settings", "draft_unsent_threshold_hours")
