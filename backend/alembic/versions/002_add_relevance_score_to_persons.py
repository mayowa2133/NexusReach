"""add relevance_score to persons

Revision ID: 002_add_relevance_score
Revises: 001_add_apollo_id
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "002_add_relevance_score"
down_revision = "001_add_apollo_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("relevance_score", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("persons", "relevance_score")
