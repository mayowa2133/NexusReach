"""Add reply content capture to outreach logs.

Revision ID: 049_add_outreach_reply_content
Revises: 048_clear_known_person_emails

Reply reconciliation (sent -> responded) now captures when the contact
replied and a short plain-text snippet of what they said, so drafting can
propose a response and the UI can show the reply inline.
"""

from alembic import op
import sqlalchemy as sa


revision = "049_add_outreach_reply_content"
down_revision = "048_clear_known_person_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_logs",
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outreach_logs",
        sa.Column("last_reply_snippet", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_logs", "last_reply_snippet")
    op.drop_column("outreach_logs", "replied_at")
