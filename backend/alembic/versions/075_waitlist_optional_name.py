"""Allow email-only waitlist signup.

Revision ID: 075_waitlist_optional_name
Revises: 074_internal_table_grants

The public landing form now asks only for an email. Optional personalization is
collected after mailbox-proven owner access on the referral dashboard.
"""

from alembic import op
import sqlalchemy as sa


revision = "075_waitlist_optional_name"
down_revision = "074_internal_table_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "waitlist_signups",
        "name",
        existing_type=sa.String(200),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE waitlist_signups SET name = '' WHERE name IS NULL")
    op.alter_column(
        "waitlist_signups",
        "name",
        existing_type=sa.String(200),
        nullable=False,
    )
