"""Add job_alert_preferences table for email notifications.

Revision ID: 021_add_job_alert_preferences
Revises: 020_add_performance_indexes
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from alembic import op

revision = "021_add_job_alert_preferences"
down_revision = "020_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_alert_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("watched_companies", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("use_starred_companies", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("keyword_filters", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("email_provider", sa.String(20), nullable=False, server_default="connected"),
        sa.Column("last_digest_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_alerts_sent", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("job_alert_preferences")
