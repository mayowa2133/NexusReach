"""Add learned email pattern fields to companies.

Revision ID: 010_add_company_email_pattern_fields
Revises: 009_add_email_confidence
"""

import sqlalchemy as sa
from alembic import op

revision = "010_add_company_email_pattern_fields"
down_revision = "009_add_email_confidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("email_pattern", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column("email_pattern_confidence", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("companies", "email_pattern_confidence")
    op.drop_column("companies", "email_pattern")
