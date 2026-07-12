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


async def main() -> None:
    query = text("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename <> 'alembic_version'
          AND NOT rowsecurity
        ORDER BY tablename
    """)
    async with async_session() as session:
        missing = [row[0] for row in (await session.execute(query)).all()]
    if missing:
        raise SystemExit("RLS is disabled for: " + ", ".join(missing))
    print("RLS enabled on every application table")


if __name__ == "__main__":
    asyncio.run(main())
