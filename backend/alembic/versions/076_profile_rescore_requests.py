"""Coalesce profile edits into a recoverable account-scoped outbox."""

from alembic import op

revision = "076_profile_rescore_requests"
down_revision = "075_waitlist_optional_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE profile_rescore_requests (
      user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      requested_version uuid NOT NULL, ticket uuid NOT NULL,
      lease_until timestamptz NOT NULL, claimed_at timestamptz)""")
    op.execute("CREATE INDEX ix_profile_rescore_requests_lease_until ON profile_rescore_requests(lease_until)")
    op.execute("ALTER TABLE profile_rescore_requests ENABLE ROW LEVEL SECURITY")
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
        REVOKE ALL ON profile_rescore_requests FROM anon;
      END IF;
      IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
        REVOKE ALL ON profile_rescore_requests FROM authenticated;
      END IF;
    END $$""")


def downgrade() -> None:
    op.drop_table("profile_rescore_requests")
