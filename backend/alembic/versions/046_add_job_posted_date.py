"""Add calendar-validated posted_date to jobs for crash-proof date sorting.

Revision ID: 046_add_job_posted_date
Revises: 045_add_job_canonical_url

Audit pass-2 P3: the previous date sort cast a substring of the free-form
`posted_at` string to ::date at query time, which raised and aborted the whole
jobs-list query on a date-shaped-but-invalid value (e.g. "2026-02-30"). This
adds a real, indexed Date column populated (and validated) at ingest. The
backfill uses a temporary, exception-swallowing parse function so invalid
strings become NULL instead of failing the migration.
"""

from alembic import op
import sqlalchemy as sa


revision = "046_add_job_posted_date"
down_revision = "045_add_job_canonical_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("posted_date", sa.Date(), nullable=True))
    op.create_index("ix_jobs_posted_date", "jobs", ["posted_date"])
    # Best-effort backfill: parse a leading YYYY-MM-DD, NULL on any invalid date.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION pg_temp.try_parse_posted_date(s text)
        RETURNS date AS $$
        BEGIN
            RETURN substring(s FROM '^\\d{4}-\\d{2}-\\d{2}')::date;
        EXCEPTION WHEN others THEN
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET posted_date = pg_temp.try_parse_posted_date(posted_at)
        WHERE posted_at IS NOT NULL AND posted_at <> ''
        """
    )
    # pg_temp function is dropped automatically at session end.


def downgrade() -> None:
    op.drop_index("ix_jobs_posted_date", table_name="jobs")
    op.drop_column("jobs", "posted_date")
