"""Add LinkedIn graph sync tables and settings columns."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019_add_linkedin_graph_tables"
down_revision = "018_add_job_experience_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linkedin_graph_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        "ix_linkedin_graph_connections_user_id",
        "linkedin_graph_connections",
        ["user_id"],
    )
    op.create_index(
        "ix_linkedin_graph_connections_linkedin_slug",
        "linkedin_graph_connections",
        ["linkedin_slug"],
    )
    op.create_index(
        "ix_linkedin_graph_connections_normalized_company_name",
        "linkedin_graph_connections",
        ["normalized_company_name"],
    )
    op.create_index(
        "ix_linkedin_graph_connections_company_linkedin_slug",
        "linkedin_graph_connections",
        ["company_linkedin_slug"],
    )

    op.create_table(
        "linkedin_graph_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("session_token_hash", sa.String(length=128), nullable=True),
        sa.Column("session_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_graph_sync_runs_user_id",
        "linkedin_graph_sync_runs",
        ["user_id"],
    )
    op.create_index(
        "ix_linkedin_graph_sync_runs_session_token_hash",
        "linkedin_graph_sync_runs",
        ["session_token_hash"],
    )

    op.add_column(
        "user_settings",
        sa.Column("linkedin_graph_connected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "user_settings",
        sa.Column("linkedin_graph_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column("linkedin_graph_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column("linkedin_graph_sync_status", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_settings",
        sa.Column("linkedin_graph_last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "linkedin_graph_last_error")
    op.drop_column("user_settings", "linkedin_graph_sync_status")
    op.drop_column("user_settings", "linkedin_graph_last_synced_at")
    op.drop_column("user_settings", "linkedin_graph_source")
    op.drop_column("user_settings", "linkedin_graph_connected")

    op.drop_index(
        "ix_linkedin_graph_sync_runs_session_token_hash",
        table_name="linkedin_graph_sync_runs",
    )
    op.drop_index(
        "ix_linkedin_graph_sync_runs_user_id",
        table_name="linkedin_graph_sync_runs",
    )
    op.drop_table("linkedin_graph_sync_runs")

    op.drop_index(
        "ix_linkedin_graph_connections_company_linkedin_slug",
        table_name="linkedin_graph_connections",
    )
    op.drop_index(
        "ix_linkedin_graph_connections_normalized_company_name",
        table_name="linkedin_graph_connections",
    )
    op.drop_index(
        "ix_linkedin_graph_connections_linkedin_slug",
        table_name="linkedin_graph_connections",
    )
    op.drop_index(
        "ix_linkedin_graph_connections_user_id",
        table_name="linkedin_graph_connections",
    )
    op.drop_table("linkedin_graph_connections")
