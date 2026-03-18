"""Add Hunter audit fields to api_usage.

Revision ID: 011_add_api_usage_audit_fields
Revises: 010_add_company_email_pattern_fields
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "011_add_api_usage_audit_fields"
down_revision = "010_add_company_email_pattern_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_usage",
        sa.Column("credits_used", sa.Float(), nullable=True),
    )
    op.add_column(
        "api_usage",
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_usage", "details")
    op.drop_column("api_usage", "credits_used")
