"""Clear work_email from the global known-people cache (audit H4).

Revision ID: 048_clear_known_person_emails
Revises: 047_enable_rls_defense_in_depth

The ``known_persons`` table is a GLOBAL, cross-user discovery cache. Storing a
``work_email`` there meant an email discovered or guessed by one user could be
surfaced to another user searching the same company — crossing the "all user
data stays scoped by user_id" boundary. The application no longer writes or
reads this column; this migration purges any emails already shared in existing
rows so the leak is closed on deploy, not just for new discoveries.

The column itself is kept (nullable) to avoid a destructive schema change and
to keep the rollback trivial. Per-user Person rows are unaffected.
"""

from alembic import op

revision = "048_clear_known_person_emails"
down_revision = "047_enable_rls_defense_in_depth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE known_persons SET work_email = NULL WHERE work_email IS NOT NULL;")


def downgrade() -> None:
    # Irreversible by design: the previously-cached emails are intentionally
    # discarded and cannot be restored.
    pass
