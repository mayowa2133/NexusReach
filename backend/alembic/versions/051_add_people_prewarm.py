"""Add on-by-default people-cache pre-warm setting.

Revision ID: 051_add_people_prewarm
Revises: 050_add_cadence_auto_draft

When enabled (default), discovering new jobs queues a discovery-only
background search for the top companies in the batch, so the known-people
cache is warm by the time the user clicks "Find People". No emails are
found, drafted, or sent — this only pre-loads contacts for speed. On by
default with an opt-out, unlike the auto-prospect feature (off by default).
"""

from alembic import op
import sqlalchemy as sa


revision = "051_add_people_prewarm"
down_revision = "050_add_cadence_auto_draft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "people_prewarm_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "people_prewarm_enabled")
