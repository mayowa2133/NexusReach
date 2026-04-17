"""Compatibility bridge for a historical local revision.

Revision ID: 025_add_auto_research_preferences_and_job_snapshots
Revises: 024_add_job_apply_url

This revision existed on a historical branch and some local databases are
already stamped to it. The current mainline no longer carries that schema
change, so this migration is intentionally a no-op bridge that restores a
valid Alembic chain for those databases without applying obsolete DDL on
fresh environments.
"""

revision = "025_add_auto_research_preferences_and_job_snapshots"
down_revision = "024_add_job_apply_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
