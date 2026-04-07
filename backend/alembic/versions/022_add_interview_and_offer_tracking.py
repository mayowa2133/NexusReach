"""Add interview rounds and offer tracking fields to jobs table.

Revision ID: 022_add_interview_and_offer_tracking
Revises: 021_add_job_alert_preferences
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "022_add_interview_and_offer_tracking"
down_revision = "021_add_job_alert_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Interview rounds: [{round, type, scheduled_at, completed, interviewer, notes}]
    op.add_column("jobs", sa.Column("interview_rounds", JSONB, nullable=True))
    # Offer details: {salary, equity, bonus, deadline, status, notes}
    op.add_column("jobs", sa.Column("offer_details", JSONB, nullable=True))
    # When the user applied
    op.add_column("jobs", sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "applied_at")
    op.drop_column("jobs", "offer_details")
    op.drop_column("jobs", "interview_rounds")
