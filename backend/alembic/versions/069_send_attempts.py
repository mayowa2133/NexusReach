"""Durable dispatch attempts and schedule generations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "069_send_attempts"
down_revision = "068_capture_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("schedule_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("send_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("provider_reference", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("uq_unresolved_send_attempt", "send_attempts", ["message_id"], unique=True,
        postgresql_where=sa.text("outcome IN ('sending', 'delivery_unknown')"))
    op.execute("ALTER TABLE send_attempts ENABLE ROW LEVEL SECURITY")
    # Old sending rows have no reliable provider outcome. Never restage them.
    op.execute("UPDATE messages SET status='delivery_unknown', scheduled_send_at=NULL WHERE status='sending'")


def downgrade():
    op.drop_table("send_attempts")
    op.drop_column("messages", "schedule_version")
