#!/usr/bin/env python3
"""Backfill ``occupation:<key>`` tags on existing Job rows.

Usage:
  python scripts/backfill_occupation_tags.py            # backfill all users
  python scripts/backfill_occupation_tags.py --user-id <uuid>
  python scripts/backfill_occupation_tags.py --limit 1000
  python scripts/backfill_occupation_tags.py --dry-run

Safe to re-run: jobs that already carry an ``occupation:`` tag are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import async_session  # noqa: E402
from app.services.occupation_backfill_service import backfill_occupation_tags  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply occupation:<key> tags to existing Job rows.",
    )
    parser.add_argument(
        "--user-id",
        help="Optional user UUID to scope the backfill to a single user.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional limit on the number of jobs to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and count without writing to the database.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, int]:
    user_id = uuid.UUID(args.user_id) if args.user_id else None
    async with async_session() as db:
        return await backfill_occupation_tags(
            db, user_id=user_id, limit=args.limit, dry_run=args.dry_run
        )


def main() -> None:
    args = parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
