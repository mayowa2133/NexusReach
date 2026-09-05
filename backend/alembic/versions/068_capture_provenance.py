"""Quarantine client assertions previously promoted into shared contact data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "068_capture_provenance"
down_revision = "067_decode_descriptions_from_other_paths"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("persons", sa.Column("provenance", sa.String(50), nullable=True))
    op.add_column("known_persons", sa.Column("provenance", sa.String(50), nullable=True))
    op.add_column("known_persons", sa.Column("verification_evidence", postgresql.JSONB(), nullable=True))
    op.execute("""
        UPDATE known_persons SET provenance='client_capture', verification_status='quarantined',
        last_verified_at=NULL, verification_evidence=NULL
        WHERE primary_source IN ('linkedin_hiring_team', 'client_capture')
          OR 'linkedin_hiring_team'=ANY(all_sources)
          OR profile_data->>'hiring_team_capture'='true'
    """)
    op.execute("""
        UPDATE persons SET provenance='client_capture', current_company_verified=false,
        current_company_verification_status='unverified',
        current_company_verification_source='client_capture',
        current_company_verification_evidence=NULL, current_company_verified_at=NULL,
        current_company_verification_confidence=NULL,
        profile_data=COALESCE(profile_data, '{}'::jsonb) ||
          jsonb_build_object('current_company_verified', false, 'company_match_confidence', 'unverified', 'provenance', 'client_capture')
        WHERE source IN ('linkedin_hiring_team','client_capture')
          OR profile_data->>'hiring_team_capture'='true'
    """)
    # These are derived caches, not user records. Invalidate all snapshots for
    # affected companies, including snapshots that omitted source metadata.
    op.execute("""
        DELETE FROM job_research_snapshots s WHERE lower(trim(s.company_name)) IN (
          SELECT kc.normalized_company_name FROM known_person_companies kc
          JOIN known_persons k ON k.id=kc.known_person_id WHERE k.verification_status='quarantined'
        ) OR s.recruiters::text LIKE '%hiring_team_capture%'
          OR s.hiring_managers::text LIKE '%hiring_team_capture%'
          OR s.peers::text LIKE '%hiring_team_capture%'
    """)


def downgrade():
    # Never restore unsupported verification when rolling back schema.
    op.drop_column("known_persons", "verification_evidence")
    op.drop_column("known_persons", "provenance")
    op.drop_column("persons", "provenance")
