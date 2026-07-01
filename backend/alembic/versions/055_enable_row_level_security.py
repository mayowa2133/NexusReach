"""Enable row level security on all public tables.

Revision ID: 055_enable_row_level_security
Revises: 054_add_resume_quality_evaluation

Supabase auto-exposes every table in the ``public`` schema through its PostgREST
REST API to the ``anon`` and ``authenticated`` roles, authenticated with the
*public* anon key that ships in the frontend bundle. With RLS disabled, anyone
holding that key can read/write every row directly at
``https://<project>.supabase.co/rest/v1/<table>``, bypassing our FastAPI layer
and its ``user_id`` scoping. Supabase's Security Advisor flags this as
"RLS disabled in public" on each table.

This migration enables RLS (``ENABLE``, *not* ``FORCE``) on every base table in
``public`` and adds **no policies**, which makes the table deny-all to the
``anon``/``authenticated`` API roles. The backend is unaffected: it connects as
the ``postgres`` role, which *owns* these tables (it runs these very
migrations), and a table owner bypasses RLS unless ``FORCE ROW LEVEL SECURITY``
is set — which we deliberately do not set. ``service_role`` (BYPASSRLS) is also
unaffected.

If a table is ever intended to be served directly through the Supabase client
from the browser, add explicit ``CREATE POLICY`` statements for it in a later
migration; until then deny-all is the correct, secure default.

Note: new tables introduced by future migrations are NOT covered automatically —
enable RLS on them in the migration that creates them.
"""

from alembic import op


revision = "055_enable_row_level_security"
down_revision = "054_add_resume_quality_evaluation"
branch_labels = None
depends_on = None


# Enable RLS on every ordinary base table in the public schema. Done dynamically
# so it covers all current tables (the 26 model tables plus alembic_version)
# without hand-maintaining a list. Owner (postgres) access is unaffected because
# we ENABLE rather than FORCE.
_ENABLE_RLS = """
DO $$
DECLARE
    tbl regclass;
BEGIN
    FOR tbl IN
        SELECT c.oid::regclass
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
    LOOP
        EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', tbl);
    END LOOP;
END
$$;
"""

_DISABLE_RLS = """
DO $$
DECLARE
    tbl regclass;
BEGIN
    FOR tbl IN
        SELECT c.oid::regclass
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
    LOOP
        EXECUTE format('ALTER TABLE %s DISABLE ROW LEVEL SECURITY', tbl);
    END LOOP;
END
$$;
"""


def upgrade() -> None:
    op.execute(_ENABLE_RLS)


def downgrade() -> None:
    op.execute(_DISABLE_RLS)
