#!/usr/bin/env python
"""Erase a person from the GLOBAL known-people cache.

The cache holds people discovered from public sources, shared across all users.
Those people never signed up, so an erasure request ("remove me") has to be
serviceable — this is that path.

Deliberately a script rather than an HTTP endpoint: requests are rare, manual,
and need a human to confirm identity. An endpoint would add public attack
surface and an enumeration oracle for no operational gain.

Usage:
    cd backend
    python scripts/erase_known_person.py --linkedin-url https://www.linkedin.com/in/someone
    python scripts/erase_known_person.py --name "Jordan Rivera"
    python scripts/erase_known_person.py --name "Jordan Rivera" --dry-run

Matching on a name alone can hit several people — always try the LinkedIn URL
first, and use --dry-run to see the count before committing.

The row is re-created if that person is discovered again by a later search. To
keep someone out permanently you need a denylist, which does not exist yet;
raise it if a request requires one.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, or_, select  # noqa: E402

from app.database import async_session  # noqa: E402
from app.models.known_person import KnownPerson  # noqa: E402
from app.services.known_people_service import (  # noqa: E402
    _normalize_name,
    erase_known_person,
)


async def _count_matches(db, linkedin_url: str | None, name: str | None) -> list[str]:
    conditions = []
    if linkedin_url:
        conditions.append(KnownPerson.linkedin_url == linkedin_url.strip())
    if name:
        conditions.append(KnownPerson.normalized_name == _normalize_name(name))
    result = await db.execute(
        select(KnownPerson.full_name, KnownPerson.linkedin_url).where(or_(*conditions))
    )
    return [
        f"{full_name or '(no name)'} — {url or 'no LinkedIn URL'}"
        for full_name, url in result.all()
    ]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linkedin-url", help="Exact profile URL (preferred)")
    parser.add_argument("--name", help="Full name; matched after normalization")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be erased without deleting",
    )
    args = parser.parse_args()

    if not args.linkedin_url and not args.name:
        parser.error("Provide --linkedin-url and/or --name")

    async with async_session() as db:
        matches = await _count_matches(db, args.linkedin_url, args.name)
        if not matches:
            print("No matching records in the known-people cache.")
            return 0

        print(f"{len(matches)} matching record(s):")
        for match in matches:
            print(f"  - {match}")

        if args.dry_run:
            print("\nDry run — nothing deleted.")
            return 0

        deleted = await erase_known_person(
            db, linkedin_url=args.linkedin_url, full_name=args.name
        )
        total = await db.execute(select(func.count()).select_from(KnownPerson))
        print(f"\nErased {deleted} record(s). {total.scalar_one()} remain in the cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
