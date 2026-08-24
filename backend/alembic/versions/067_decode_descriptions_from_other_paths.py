"""Decode escaped descriptions stored by the non-crawl ingest paths.

Revision ID: 067_decode_descriptions_from_other_paths
Revises: 066_decode_escaped_job_descriptions

Migration 066 repaired the rows that existed then, and the ingest fix that went
with it was applied to one of the three paths that store a job. The other two
kept storing Greenhouse's HTML-escaped `content` verbatim, so the defect came
straight back: one career-page search for `figma` added 162 rows, every one of
them escaped again.

The code fix this time is structural -- all three paths now run one
`prepare_raw_job` -- so this backfill is not expected to be needed a third time.

Same predicate as 066, and the same reason for it: a row counts as escaped only
when it holds `&lt;` and no real `<` anywhere. A description carrying real markup
*and* escaped entities is a posting quoting a code sample, and decoding it would
turn the sample the reader is meant to see into layout.

Tags are deliberately not backfilled here. Inferring an occupation means running
the Python classifier over title and description, which a SQL migration cannot
do, and `_refresh_existing_job` already merges newly inferred `occupation:*` tags
on the next refresh that touches a row -- so tagged-ness heals on its own now
that every path infers them.
"""

from alembic import op

revision = "067_decode_descriptions_from_other_paths"
down_revision = "066_decode_escaped_job_descriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE jobs
        SET description = replace(
                replace(
                    replace(
                        replace(
                            replace(description, '&lt;', '<'),
                        '&gt;', '>'),
                    '&quot;', '"'),
                '&#39;', ''''),
            '&amp;', '&')
        WHERE description IS NOT NULL
          AND description LIKE '%&lt;%'
          AND description NOT LIKE '%<%'
        """
    )


def downgrade() -> None:
    """No-op: decoded and never-escaped rows are indistinguishable afterwards."""
