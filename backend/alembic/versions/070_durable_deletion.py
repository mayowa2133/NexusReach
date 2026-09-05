"""Deletion receipts, retry actions, and revoked-subject barrier."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision = '070_durable_deletion'
down_revision = '069_send_attempts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_tombstones',
        sa.Column('subject', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('upstream_deleted_at', sa.DateTime(timezone=True)))
    op.create_table('deletion_requests',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('request_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('receipt_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)))
    op.create_table('deletion_actions',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('request_id', pg.UUID(as_uuid=True), sa.ForeignKey('deletion_requests.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('target', sa.String(1000)),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_deletion_actions_next_attempt_at', 'deletion_actions', ['next_attempt_at'])
    for table in ('auth_tombstones', 'deletion_requests', 'deletion_actions'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def downgrade():
    raise RuntimeError('Revocation and pending erasure records must not be dropped on rollback')
