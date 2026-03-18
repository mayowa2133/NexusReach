"""Add email_confidence column to persons table.

Stores confidence score (0-100) for pattern-suggested emails that could
not be SMTP-verified. NULL means no confidence data (email was verified
through another source or not yet looked up).

Revision ID: 009_add_email_confidence
Revises: 008_seed_smtp_blocklist
"""

import sqlalchemy as sa
from alembic import op

revision = "009_add_email_confidence"
down_revision = "008_seed_smtp_blocklist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persons",
        sa.Column("email_confidence", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persons", "email_confidence")
