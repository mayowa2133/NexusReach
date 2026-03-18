"""Add current-company verification fields to persons.

Revision ID: 012_add_current_company_verification_fields
Revises: 011_add_api_usage_audit_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "012_add_current_company_verification_fields"
down_revision = "011_add_api_usage_audit_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persons",
        sa.Column("current_company_verified", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("current_company_verification_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("current_company_verification_source", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("current_company_verification_confidence", sa.Integer(), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("current_company_verification_evidence", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("current_company_verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persons", "current_company_verified_at")
    op.drop_column("persons", "current_company_verification_evidence")
    op.drop_column("persons", "current_company_verification_confidence")
    op.drop_column("persons", "current_company_verification_source")
    op.drop_column("persons", "current_company_verification_status")
    op.drop_column("persons", "current_company_verified")
