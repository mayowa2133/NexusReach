"""Deny browser database roles direct access to internal security state."""

from alembic import op


revision = "074_internal_table_grants"
down_revision = "073_paid_work_reservations"
branch_labels = None
depends_on = None


_INTERNAL_TABLES = (
    "send_attempts",
    "auth_tombstones",
    "deletion_requests",
    "deletion_actions",
    "referral_campaigns",
    "referral_credentials",
    "referral_credits",
    "paid_budget_buckets",
    "paid_reservations",
)


def upgrade():
    tables = ", ".join(_INTERNAL_TABLES)
    # Supabase may apply browser-role default grants to new public-schema tables.
    # These records contain revocation, bearer, dispatch, and billing state and
    # are reachable only through authenticated server APIs.
    op.execute(f"REVOKE ALL PRIVILEGES ON TABLE {tables} FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL PRIVILEGES ON TABLE {tables} FROM anon;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL PRIVILEGES ON TABLE {tables} FROM authenticated;
          END IF;
        END
        $$
        """
    )


def downgrade():
    raise RuntimeError("Direct browser access to internal security tables must not be restored")
