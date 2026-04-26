"""Add LinkedIn follow signal storage."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "038_add_linkedin_graph_follows"
down_revision = "037_add_cadence_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linkedin_graph_follows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("linkedin_slug", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("headline", sa.String(length=255), nullable=True),
        sa.Column("current_company_name", sa.String(length=255), nullable=True),
        sa.Column("normalized_company_name", sa.String(length=255), nullable=True),
        sa.Column("company_linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("company_linkedin_slug", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_graph_follows_user_id",
        "linkedin_graph_follows",
        ["user_id"],
    )
    op.create_index(
        "ix_linkedin_graph_follows_entity_type",
        "linkedin_graph_follows",
        ["entity_type"],
    )
    op.create_index(
        "ix_linkedin_graph_follows_linkedin_slug",
        "linkedin_graph_follows",
        ["linkedin_slug"],
    )
    op.create_index(
        "ix_linkedin_graph_follows_normalized_company_name",
        "linkedin_graph_follows",
        ["normalized_company_name"],
    )
    op.create_index(
        "ix_linkedin_graph_follows_company_linkedin_slug",
        "linkedin_graph_follows",
        ["company_linkedin_slug"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_linkedin_graph_follows_company_linkedin_slug",
        table_name="linkedin_graph_follows",
    )
    op.drop_index(
        "ix_linkedin_graph_follows_normalized_company_name",
        table_name="linkedin_graph_follows",
    )
    op.drop_index(
        "ix_linkedin_graph_follows_linkedin_slug",
        table_name="linkedin_graph_follows",
    )
    op.drop_index(
        "ix_linkedin_graph_follows_entity_type",
        table_name="linkedin_graph_follows",
    )
    op.drop_index(
        "ix_linkedin_graph_follows_user_id",
        table_name="linkedin_graph_follows",
    )
    op.drop_table("linkedin_graph_follows")
