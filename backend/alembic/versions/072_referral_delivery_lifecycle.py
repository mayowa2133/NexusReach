"""Bound the legacy referral transition and make notification outbox retryable."""

from alembic import op
import sqlalchemy as sa

revision = "072_referral_delivery_lifecycle"
down_revision = "071_referral_security"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "referral_campaigns",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "referral_campaigns",
        sa.Column("legacy_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE referral_campaigns SET legacy_until = created_at + interval '7 days' "
        "WHERE legacy_until IS NULL"
    )
    op.alter_column("referral_campaigns", "legacy_until", nullable=False)
    op.add_column(
        "referral_credits",
        sa.Column("notification_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "referral_credits",
        sa.Column(
            "notification_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade():
    raise RuntimeError("Referral transition and outbox state must not be removed")
