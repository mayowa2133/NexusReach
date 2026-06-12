"""Add opt-in auto-drafting of due cadence follow-ups.

Revision ID: 050_add_cadence_auto_draft
Revises: 049_add_outreach_reply_content

When enabled, the weekly cadence digest pre-drafts messages for due
follow-up actions (draft-first: nothing is sent automatically). Opt-in
because each draft is an LLM call.
"""

from alembic import op
import sqlalchemy as sa


revision = "050_add_cadence_auto_draft"
down_revision = "049_add_outreach_reply_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "cadence_auto_draft_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "cadence_auto_draft_enabled")
