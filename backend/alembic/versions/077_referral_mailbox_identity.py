"""Version referral identity keys for provider-aware canonicalization."""

from alembic import op

revision = "077_referral_mailbox_identity"
down_revision = "076_profile_rescore_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The service reconciles encrypted identity keys while holding its campaign
    # lock. Migration code never loads application secrets.
    op.execute("ALTER TABLE referral_campaigns ADD COLUMN identity_version integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE referral_campaigns ALTER COLUMN identity_version SET DEFAULT 2")
    op.execute("ALTER TABLE referral_campaigns ADD COLUMN unresolved_legacy_identities integer NOT NULL DEFAULT 0")


def downgrade() -> None:
    raise RuntimeError("Canonical anti-replay identities must not be reverted")
