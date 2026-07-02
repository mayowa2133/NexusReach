"""Add the missing hot-path indexes on jobs.

Revision ID: 056_add_jobs_performance_indexes
Revises: 055_enable_row_level_security

Migration 020 already covers the dedup pair probe
(``ix_jobs_user_source_external``) and plain user scans
(``ix_jobs_user_source``), but three feed hot paths still had none:

- ``ix_jobs_user_match_score``: the default feed sort is
  ``WHERE user_id = ? ORDER BY match_score DESC NULLS LAST`` on every
  ``GET /api/jobs``.
- ``ix_jobs_tags``: GIN for the Startup filter and the occupation-chip
  filters, both of which use ``tags @> ARRAY[...]`` (un-indexed, contains()
  unnests row by row).
- ``ix_jobs_user_prewarm_pending``: partial index for the warming-count
  query the frontend polls every few seconds while people pre-warm runs.

No RLS work needed: this migration creates no new tables.
"""

from alembic import op
import sqlalchemy as sa


revision = "056_add_jobs_performance_indexes"
down_revision = "055_enable_row_level_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_user_match_score",
        "jobs",
        ["user_id", sa.text("match_score DESC NULLS LAST")],
    )
    op.create_index("ix_jobs_tags", "jobs", ["tags"], postgresql_using="gin")
    op.create_index(
        "ix_jobs_user_prewarm_pending",
        "jobs",
        ["user_id", "created_at"],
        postgresql_where=sa.text("people_prewarm_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_user_prewarm_pending", table_name="jobs")
    op.drop_index("ix_jobs_tags", table_name="jobs")
    op.drop_index("ix_jobs_user_match_score", table_name="jobs")
