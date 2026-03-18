"""add apollo_id to persons

Revision ID: 001_add_apollo_id
Revises:
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001_add_apollo_id"
down_revision = "000_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("apollo_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("persons", "apollo_id")
