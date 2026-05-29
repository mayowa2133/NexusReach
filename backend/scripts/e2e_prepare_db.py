"""Create the isolated E2E database when it does not exist."""

from __future__ import annotations

import asyncio
import re

import asyncpg
from sqlalchemy.engine import make_url

from app.config import settings


async def main() -> None:
    if settings.environment != "e2e":
        raise SystemExit("Refusing to prepare a database outside NEXUSREACH_ENVIRONMENT=e2e.")

    url = make_url(settings.database_url)
    database = url.database
    if not database:
        raise SystemExit("NEXUSREACH_DATABASE_URL must include a database name.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        raise SystemExit("E2E database name may only contain letters, numbers, and underscores.")
    if "e2e" not in database.lower():
        raise SystemExit("E2E database name must include 'e2e' to allow destructive reset.")

    maintenance_url = url.set(drivername="postgresql", database="postgres")
    conn = await asyncpg.connect(maintenance_url.render_as_string(hide_password=False))
    try:
        await conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1
              AND pid <> pg_backend_pid()
            """,
            database,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await conn.execute(f'CREATE DATABASE "{database}"')
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
