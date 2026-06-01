"""Enable Row Level Security on all public tables (defense-in-depth).

Revision ID: 047_enable_rls_defense_in_depth
Revises: 046_add_job_posted_date

Vibe-checklist review finding #1 (CRITICAL) — see VIBE_CHECKLIST_REVIEW.md.

Supabase exposes the `public` schema over its auto-generated PostgREST Data API
to anyone holding the anon key, and that anon key ships publicly in the Vercel
frontend bundle (VITE_SUPABASE_ANON_KEY). Our application never uses that API
(the backend talks to Postgres directly via NEXUSREACH_DATABASE_URL and scopes
every query by user_id), but tables created by Alembic land in `public` WITHOUT
RLS — so they are reachable at https://<project>.supabase.co/rest/v1/<table>
unless the Data API is disabled or RLS is enabled.

This migration ENABLEs (not FORCEs) RLS on every application table and creates
NO policies. With no policy, that is a deny-all for the `anon` and
`authenticated` API roles, while the backend is unaffected: Supabase's
`postgres` role — used by the direct DATABASE_URL connection and the owner of
these Alembic-created tables — has BYPASSRLS and is exempt.

This is DEFENSE-IN-DEPTH. The primary, complete control is to disable the Data
API (or remove `public` from the exposed schemas) in the Supabase dashboard.
Verify the gap is closed either way:

    curl 'https://<project>.supabase.co/rest/v1/users?select=*&limit=1' \
        -H "apikey: <anon-key>"

A permission error means good; returned rows mean still exposed.

SAFETY: this is safe only while the backend connects as a BYPASSRLS/owner role
(Supabase `postgres` is). If you ever switch the app to a restricted DB role,
add per-table policies first or this becomes a deny-all for the app too.
`downgrade()` disables RLS again.
"""

from alembic import op


revision = "047_enable_rls_defense_in_depth"
down_revision = "046_add_job_posted_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable (not force) RLS on every application table that doesn't already
    # have it. alembic_version is migration bookkeeping; spatial_ref_sys is
    # PostGIS-owned (and may not be alterable) — skip both.
    op.execute(
        """
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename NOT IN ('alembic_version', 'spatial_ref_sys')
                  AND rowsecurity = false
            LOOP
                EXECUTE format(
                    'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;',
                    r.tablename
                );
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Reverses this migration. NOTE: if you later add real RLS policies to a
    # table, downgrading this migration will disable RLS on it as well.
    op.execute(
        """
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename NOT IN ('alembic_version', 'spatial_ref_sys')
                  AND rowsecurity = true
            LOOP
                EXECUTE format(
                    'ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY;',
                    r.tablename
                );
            END LOOP;
        END $$;
        """
    )
