"""Exit non-zero if any application table lacks PostgreSQL RLS."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# ``python scripts/verify_rls.py`` makes ``scripts/`` the first import root,
# not the backend directory.  Add the repository's backend root explicitly so
# the exact command used by CI and operators can import the application package.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.database import async_session  # noqa: E402


_SERVER_ONLY_TABLES = (
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


async def main() -> None:
    query = text("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename <> 'alembic_version'
          AND NOT rowsecurity
        ORDER BY tablename
    """)
    browser_grants_query = text("""
        SELECT roles.rolname, tables.table_name
        FROM pg_roles AS roles
        CROSS JOIN unnest(CAST(:tables AS text[])) AS tables(table_name)
        WHERE roles.rolname IN ('anon', 'authenticated')
          AND (
            has_table_privilege(roles.rolname, 'public.' || quote_ident(tables.table_name), 'SELECT')
            OR has_table_privilege(roles.rolname, 'public.' || quote_ident(tables.table_name), 'INSERT')
            OR has_table_privilege(roles.rolname, 'public.' || quote_ident(tables.table_name), 'UPDATE')
            OR has_table_privilege(roles.rolname, 'public.' || quote_ident(tables.table_name), 'DELETE')
            OR has_table_privilege(roles.rolname, 'public.' || quote_ident(tables.table_name), 'TRUNCATE')
            OR has_table_privilege(roles.rolname, 'public.' || quote_ident(tables.table_name), 'REFERENCES')
            OR has_table_privilege(roles.rolname, 'public.' || quote_ident(tables.table_name), 'TRIGGER')
          )
        ORDER BY roles.rolname, tables.table_name
    """)
    async with async_session() as session:
        missing = [row[0] for row in (await session.execute(query)).all()]
        browser_grants = [
            f"{row[0]}:{row[1]}"
            for row in (
                await session.execute(
                    browser_grants_query,
                    {"tables": list(_SERVER_ONLY_TABLES)},
                )
            ).all()
        ]
    if missing:
        raise SystemExit("RLS is disabled for: " + ", ".join(missing))
    if browser_grants:
        raise SystemExit(
            "Browser roles can access server-only tables: " + ", ".join(browser_grants)
        )
    print("RLS enabled on every application table; internal tables deny browser roles")


if __name__ == "__main__":
    asyncio.run(main())
