"""Add search_preferences table.

Revision ID: 006_add_search_preferences
Revises: 005_add_notifications
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision = "006_add_search_preferences"
down_revision = "005_add_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.String(500), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("remote_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
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
    op.create_index("ix_search_preferences_user", "search_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_search_preferences_user")
    op.drop_table("search_preferences")
