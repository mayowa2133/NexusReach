"""Run the one-time identity backfill before reopening referral traffic."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session  # noqa: E402
from app.services.referral_credentials import campaign  # noqa: E402


async def main() -> None:
    async with async_session() as db:
        row, _ = await campaign(db)
        await db.commit()
        print(f"Identity version: {row.identity_version}; unresolved legacy identities: {row.unresolved_legacy_identities}")
        if row.unresolved_legacy_identities:
            print("New Gmail referral rewards remain paused for this campaign; mailbox verification still works.")


if __name__ == "__main__":
    asyncio.run(main())
