"""Add target_occupations to profiles."""

from alembic import op
import sqlalchemy as sa


revision = "040_add_target_occupations"
down_revision = "039_add_resume_reuse_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "target_occupations",
            sa.ARRAY(sa.String()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("profiles", "target_occupations")
