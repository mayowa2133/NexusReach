"""Decode job descriptions that were stored HTML-escaped.

Revision ID: 066_decode_escaped_job_descriptions
Revises: 065_add_waitlist_target_occupation

Greenhouse returns its ``content`` field HTML-escaped, and the ingest stored it
verbatim. The Job detail page sanitizes the description and inserts it as HTML,
so escaped input survives sanitizing untouched and reaches the reader as angle
brackets and tag names -- the description opened with a literal
``<div class="content-intro"><h2><strong>About Anthropic</strong></h2>`` on
screen. Every Greenhouse row was affected.

The ingest now decodes on the way in. This repairs the rows already stored.

The predicate is the same one the ingest uses, and it is deliberately not keyed
on ``source``: Ashby and Jobicy each had a few escaped rows too, so a per-source
UPDATE would have left them broken. A row is treated as escaped only when it
contains ``&lt;`` and no real ``<`` anywhere -- a description that holds real
markup *and* escaped entities is a document quoting a code sample, and decoding
it would turn the sample into layout. On this database that predicate separated
1290 escaped rows from 5 rows carrying both.

Not reversible in a useful sense: re-escaping the decoded rows would also
re-escape the ones that were always fine, since after this runs the two are
indistinguishable. ``downgrade`` is therefore a no-op rather than a lie.
"""

from alembic import op

revision = "066_decode_escaped_job_descriptions"
down_revision = "065_add_waitlist_target_occupation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres has no HTML entity decoder, and the affected content uses a small
    # fixed set: the five XML predefined entities are what Greenhouse emits.
    # `&amp;` is unescaped last so that `&amp;lt;` -- an escaped ampersand
    # followed by "lt;" -- does not turn into a tag delimiter on the way through.
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
