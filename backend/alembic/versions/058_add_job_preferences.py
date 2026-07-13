"""Add structured job eligibility and negative preferences to profiles.

Revision ID: 058_add_job_preferences
Revises: 057_add_waitlist_signups
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "058_add_job_preferences"
down_revision = "057_add_waitlist_signups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "job_preferences",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("profiles", "job_preferences")
