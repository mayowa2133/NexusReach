"""Add indexed canonical_url to jobs for fast URL dedup (audit H7).

Revision ID: 045_add_job_canonical_url
Revises: 044_add_job_refresh_observability
"""

from alembic import op
import sqlalchemy as sa


revision = "045_add_job_canonical_url"
down_revision = "044_add_job_refresh_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("canonical_url", sa.String(length=1000), nullable=True))
    op.create_index("ix_jobs_canonical_url", "jobs", ["canonical_url"])
    # Best-effort backfill for the common case: URLs with no query/fragment can
    # be canonicalized in SQL (strip trailing slash). ATS-specific canonical
    # forms and query-bearing URLs are left NULL and backfilled lazily by the
    # service on the next dedup/refresh pass.
    op.execute(
        """
        UPDATE jobs
        SET canonical_url = rtrim(split_part(split_part(url, '?', 1), '#', 1), '/')
        WHERE url IS NOT NULL
          AND url <> ''
          AND position('?' in url) = 0
          AND position('#' in url) = 0
        """
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_canonical_url", table_name="jobs")
    op.drop_column("jobs", "canonical_url")
