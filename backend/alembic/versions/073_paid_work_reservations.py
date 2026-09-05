"""Atomic account and deployment budgets for paid provider work."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "073_paid_work_reservations"
down_revision = "072_referral_delivery_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paid_budget_buckets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(80), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("calls_settled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("calls_reserved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_settled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_reserved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active_operations", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("scope", "period", name="uq_paid_budget_scope_period"),
    )
    op.create_table(
        "paid_reservations",
        sa.Column("operation_id", sa.String(160), primary_key=True),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service", sa.String(60), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("actual_tokens", sa.Integer()),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_paid_reservations_user_id", "paid_reservations", ["user_id"])
    op.create_index("ix_paid_reservations_state", "paid_reservations", ["state"])
    op.create_index("ix_paid_reservations_expires_at", "paid_reservations", ["expires_at"])
    for table in ("paid_budget_buckets", "paid_reservations"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade():
    raise RuntimeError("Paid-work accounting must not be removed on rollback")
