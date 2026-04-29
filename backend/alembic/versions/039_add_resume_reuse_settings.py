"""Add resume artifact reuse settings."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "039_add_resume_reuse_settings"
down_revision = "038_add_linkedin_graph_follows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "resume_auto_reuse_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "resume_artifacts",
        sa.Column("reused_from_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "resume_artifacts",
        sa.Column("reuse_score", sa.Float(), nullable=True),
    )
    op.create_foreign_key(
        "fk_resume_artifacts_reused_from_artifact_id",
        "resume_artifacts",
        "resume_artifacts",
        ["reused_from_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_resume_artifacts_reused_from_artifact_id",
        "resume_artifacts",
        type_="foreignkey",
    )
    op.drop_column("resume_artifacts", "reuse_score")
    op.drop_column("resume_artifacts", "reused_from_artifact_id")
    op.drop_column("user_settings", "resume_auto_reuse_enabled")
