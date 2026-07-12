"""Exit non-zero if any application table lacks PostgreSQL RLS."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.database import async_session


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
