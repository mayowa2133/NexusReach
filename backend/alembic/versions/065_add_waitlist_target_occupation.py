"""Add target_occupation to waitlist_signups.

Revision ID: 065_add_waitlist_target_occupation
Revises: 064_known_people_minimization

The waitlist asked for a target role as free text, which is unusable for the two
things we actually want it for: seeding a member's saved searches at launch
(``profile._seed_saved_searches`` takes occupation *keys*) and inviting by
cohort. "SWE" / "Software Engineer" / "swe new grad" are three strings for one
segment.

This stores a validated key from the occupation taxonomy instead. The existing
free-text ``target_role`` is kept rather than migrated: it still receives input
from the picker's fallback path (used when the taxonomy can't be fetched), and
holds the more specific phrasing people typed before this column existed.

ALTERs a table that already has RLS enabled (migration 057), so per the
project's RLS rule no new ENABLE ROW LEVEL SECURITY is needed.
"""

from alembic import op
import sqlalchemy as sa


revision = "065_add_waitlist_target_occupation"
down_revision = "064_known_people_minimization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: rows predate this column, and the picker falls back to free text
    # when the taxonomy is unreachable, so a value is never guaranteed.
    op.add_column(
        "waitlist_signups",
        sa.Column("target_occupation", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("waitlist_signups", "target_occupation")
