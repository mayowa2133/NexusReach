"""Add rewrite_decisions to resume_artifacts and resume_auto_accept_inferred to profiles.

Revision ID: 035_add_resume_review_fields
Revises: 034_add_resume_artifacts
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "035_add_resume_review_fields"
down_revision = "034_add_resume_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resume_artifacts",
        sa.Column(
            "rewrite_decisions",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "profiles",
        sa.Column(
            "resume_auto_accept_inferred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("profiles", "resume_auto_accept_inferred")
    op.drop_column("resume_artifacts", "rewrite_decisions")
