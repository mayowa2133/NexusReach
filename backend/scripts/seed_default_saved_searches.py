"""Backfill a default enabled saved search for users who have none.

Fixes accounts that onboarded before the occupation-aware seed fix: a user with
a profile but zero saved searches is invisible to the background refresh /
ATS-board discovery pipeline (both are gated on an enabled `SearchPreference`),
so their feed silently freezes at their last manual "Discover Jobs" run.

Idempotent and safe to re-run: `_seed_saved_searches` skips any user that already
has at least one saved search. Run from inside an environment that can reach the
DB (e.g. Railway), since the seed reads target_occupations/target_roles:

    PYTHONPATH=backend python backend/scripts/seed_default_saved_searches.py
"""

import asyncio

from sqlalchemy import func, select

from app.database import async_session
from app.models.profile import Profile
from app.models.search_preference import SearchPreference
from app.routers.profile import _seed_saved_searches


async def main() -> None:
    async with async_session() as db:
        profiles = (await db.execute(select(Profile))).scalars().all()
        print(f"profiles: {len(profiles)}")
        seeded_users = 0
        for profile in profiles:
            before = (
                await db.execute(
                    select(func.count())
                    .select_from(SearchPreference)
                    .where(SearchPreference.user_id == profile.user_id)
                )
            ).scalar() or 0
            if before:
                continue  # already has saved searches — skip
            await _seed_saved_searches(db, profile.user_id, profile)
            after = (
                await db.execute(
                    select(func.count())
                    .select_from(SearchPreference)
                    .where(SearchPreference.user_id == profile.user_id)
                )
            ).scalar() or 0
            if after > before:
                seeded_users += 1
                print(f"  seeded {after} saved search(es) for user {profile.user_id}")
            else:
                print(
                    f"  user {profile.user_id}: no target_roles/target_occupations "
                    "to seed from — skipped"
                )
        print(f"done: seeded {seeded_users} user(s)")


if __name__ == "__main__":
    asyncio.run(main())
