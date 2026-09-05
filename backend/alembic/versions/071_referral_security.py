"""Campaign credit uniqueness and expiring scoped credentials."""
from alembic import op
revision = '071_referral_security'
down_revision = '070_durable_deletion'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE referral_campaigns (
      id varchar(64) PRIMARY KEY, sealed_key varchar(1000), closed_at timestamptz)''')
    op.execute('''CREATE TABLE referral_credentials (
      token_hash varchar(64) PRIMARY KEY, signup_id uuid NOT NULL REFERENCES waitlist_signups(id) ON DELETE CASCADE,
      kind varchar(20) NOT NULL, expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now())''')
    op.execute('CREATE INDEX ix_referral_credentials_signup_id ON referral_credentials(signup_id)')
    op.execute('''CREATE TABLE referral_credits (
      id uuid PRIMARY KEY, campaign_id varchar(64) NOT NULL REFERENCES referral_campaigns(id),
      fingerprint varchar(64) NOT NULL, referrer_id uuid REFERENCES waitlist_signups(id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now(), notification_status varchar(20) NOT NULL,
      CONSTRAINT uq_referral_campaign_identity UNIQUE(campaign_id, fingerprint))''')
    for table in ('referral_campaigns', 'referral_credentials', 'referral_credits'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')


def downgrade():
    raise RuntimeError('Campaign anti-replay state must not be dropped on rollback')
