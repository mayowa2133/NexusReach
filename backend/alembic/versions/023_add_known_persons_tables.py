"""Add global known_persons and known_person_companies tables.

Revision ID: 023_add_known_persons_tables
Revises: 022_add_interview_and_offer_tracking
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision = "023_add_known_persons_tables"
down_revision = "022_add_interview_and_offer_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "known_persons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("seniority", sa.String(100), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True, unique=True),
        sa.Column("github_url", sa.String(500), nullable=True),
        sa.Column("work_email", sa.String(255), nullable=True),
        sa.Column("apollo_id", sa.String(100), nullable=True, unique=True),
        sa.Column("profile_data", JSONB, nullable=True),
        sa.Column("github_data", JSONB, nullable=True),
        sa.Column("primary_source", sa.String(50), nullable=False),
        sa.Column("all_sources", ARRAY(sa.Text), nullable=True),
        sa.Column("discovery_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_status", sa.String(50), server_default="fresh"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("ix_known_persons_normalized_name", "known_persons", ["normalized_name"])
    op.create_index(
        "ix_known_persons_name_title",
        "known_persons",
        ["normalized_name", "title"],
    )

    op.create_table(
        "known_person_companies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "known_person_id",
            UUID(as_uuid=True),
            sa.ForeignKey("known_persons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("normalized_company_name", sa.String(255), nullable=False),
        sa.Column("company_domain", sa.String(255), nullable=True),
        sa.Column("title_at_company", sa.String(255), nullable=True),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("verification_status", sa.String(50), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "known_person_id", "normalized_company_name",
            name="uq_known_person_company",
        ),
    )

    op.create_index(
        "ix_known_person_companies_normalized_company",
        "known_person_companies",
        ["normalized_company_name"],
    )


def downgrade() -> None:
    op.drop_table("known_person_companies")
    op.drop_table("known_persons")
