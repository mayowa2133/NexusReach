"""Reset the deterministic E2E user before running real browser tests."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from app.config import settings
from app.database import async_session
from app.services.account_service import delete_user_data


async def main() -> None:
    if settings.environment != "e2e":
        raise SystemExit("Refusing to reset data outside NEXUSREACH_ENVIRONMENT=e2e.")

    user_id = uuid.UUID(
        os.getenv(
            "NEXUSREACH_E2E_USER_ID",
            "11111111-1111-4111-8111-111111111111",
        )
    )

    async with async_session() as db:
        await delete_user_data(db, user_id)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"E2E user reset failed: {exc}", file=sys.stderr)
        raise
