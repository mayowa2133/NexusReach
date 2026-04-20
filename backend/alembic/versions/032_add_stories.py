"""Add stories table.

Revision ID: 032_add_stories
Revises: 031_add_job_research_snapshots
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "032_add_stories"
down_revision = "031_add_job_research_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("situation", sa.Text, nullable=True),
        sa.Column("action", sa.Text, nullable=True),
        sa.Column("result", sa.Text, nullable=True),
        sa.Column("impact_metric", sa.String(255), nullable=True),
        sa.Column("role_focus", sa.String(255), nullable=True),
        sa.Column("tags", JSONB, nullable=True),
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
    op.create_index("ix_stories_user_id", "stories", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_stories_user_id")
    op.drop_table("stories")
