"""Add email verification metadata fields to persons.

Revision ID: 013_add_email_verification_fields
Revises: 012_add_current_company_verification_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "013_add_email_verification_fields"
down_revision = "012_add_current_company_verification_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "persons",
        sa.Column("email_verification_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("email_verification_method", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("email_verification_label", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("email_verification_evidence", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "persons",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        UPDATE persons
        SET
            email_verification_status = CASE
                WHEN work_email IS NULL THEN NULL
                WHEN email_source IN ('pattern_suggestion', 'pattern_suggestion_learned') THEN 'best_guess'
                WHEN email_verified = TRUE THEN 'verified'
                WHEN work_email IS NOT NULL THEN 'unknown'
                ELSE NULL
            END,
            email_verification_method = CASE
                WHEN work_email IS NULL THEN NULL
                WHEN email_source IN ('pattern_smtp', 'pattern_smtp_gravatar') THEN 'smtp_pattern'
                WHEN email_source = 'apollo' THEN 'provider_verified'
                WHEN email_source IN ('pattern_suggestion', 'pattern_suggestion_learned') THEN 'none'
                WHEN work_email IS NOT NULL THEN 'none'
                ELSE NULL
            END,
            email_verification_label = CASE
                WHEN work_email IS NULL THEN NULL
                WHEN email_source IN ('pattern_smtp', 'pattern_smtp_gravatar') AND email_verified = TRUE THEN 'SMTP-verified'
                WHEN email_source = 'apollo' AND email_verified = TRUE THEN 'Provider-verified'
                WHEN email_source = 'pattern_suggestion_learned' THEN 'Best guess from learned company pattern'
                WHEN email_source = 'pattern_suggestion' THEN 'Best guess from generic pattern fallback'
                WHEN email_verified = TRUE THEN 'Verified'
                WHEN work_email IS NOT NULL THEN 'Verification unknown'
                ELSE NULL
            END,
            email_verification_evidence = CASE
                WHEN work_email IS NULL THEN NULL
                WHEN email_source IN ('pattern_smtp', 'pattern_smtp_gravatar') AND email_verified = TRUE
                    THEN 'Backfilled from existing SMTP pattern verification.'
                WHEN email_source = 'apollo' AND email_verified = TRUE
                    THEN 'Backfilled from existing provider-verified email.'
                WHEN email_source = 'pattern_suggestion_learned'
                    THEN 'Backfilled from existing learned company-pattern best guess.'
                WHEN email_source = 'pattern_suggestion'
                    THEN 'Backfilled from existing generic-pattern best guess.'
                WHEN email_verified = TRUE
                    THEN 'Backfilled from existing verified email.'
                WHEN work_email IS NOT NULL
                    THEN 'Backfilled from existing saved email with unknown verification provenance.'
                ELSE NULL
            END,
            email_verified_at = CASE
                WHEN email_verified = TRUE AND work_email IS NOT NULL THEN created_at
                ELSE NULL
            END
        """
    )


def downgrade() -> None:
    op.drop_column("persons", "email_verified_at")
    op.drop_column("persons", "email_verification_evidence")
    op.drop_column("persons", "email_verification_label")
    op.drop_column("persons", "email_verification_method")
    op.drop_column("persons", "email_verification_status")
