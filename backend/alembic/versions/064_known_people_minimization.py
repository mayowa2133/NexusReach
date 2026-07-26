"""Drop the unused work_email column from the global known-people cache.

Revision ID: 064_known_people_minimization
Revises: 063_split_waitlist_verification_token

``known_persons`` is deliberately NOT user-scoped — it is a shared cache of
people discovered from public sources, so a row describes a third party who
never interacted with the product. Data minimization matters more there than
anywhere else in the schema.

``work_email`` has been dead for a while: migration 048 nulled every value and
``known_people_service`` explicitly refuses to cache one (a discovered email
belongs to the user who found it, on their own ``Person`` row, not in a shared
table). Dropping the column removes the possibility of it being silently
repopulated by a future change.

Companion change in the same pass: expired rows are now actually deleted by
``known_people_service.purge_expired_records`` rather than only flagged, so the
cache stops accumulating third-party PII indefinitely.
"""

from alembic import op
import sqlalchemy as sa


revision = "064_known_people_minimization"
down_revision = "063_split_waitlist_verification_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("known_persons", "work_email")


def downgrade() -> None:
    # Restores the column, never the values — migration 048 discarded those on
    # purpose and nothing has written it since.
    op.add_column(
        "known_persons", sa.Column("work_email", sa.String(255), nullable=True)
    )
