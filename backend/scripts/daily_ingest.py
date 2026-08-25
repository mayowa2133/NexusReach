#!/usr/bin/env python3
"""Run the day's job discovery for one workspace, and report what changed.

Usage:
  python scripts/daily_ingest.py                       # startup + default modes
  python scripts/daily_ingest.py --mode startup        # one mode only
  python scripts/daily_ingest.py --user-id <uuid>      # a specific workspace
  python scripts/daily_ingest.py --dry-run             # count, don't ingest

This exists so the ingest is a thing you can run rather than a function you have
to remember how to call. Gideon's daily film runner shells out to it before
cutting anything, because a film whose whole claim is "these arrived overnight"
is only true if something actually went and looked overnight.

Safe to re-run. That was not always so: two paths could store the same posting in
one flush and Postgres rejected the statement, which aborted the run and left the
second attempt storing nothing. Both are fixed, and re-runnability is the point
of this script -- a daily job that cannot be run twice is a daily job that fails
on the first retry.

Prints a JSON summary on stdout so a caller can log it and a human can read it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select  # noqa: E402

from app.database import async_session  # noqa: E402
from app.models import Job, Profile  # noqa: E402
from app.services.jobs.discovery import discover_jobs  # noqa: E402

# Startup first: it is the mode the daily films are cut from, so if the run has
# to be cut short the thing they depend on has already happened.
MODES = ("startup", "default")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", help="Workspace to ingest for; defaults to the first profile.")
    parser.add_argument("--mode", choices=MODES, action="append", help="Repeatable; defaults to all.")
    parser.add_argument("--dry-run", action="store_true", help="Report current counts and exit.")
    return parser.parse_args()


async def _counts(db) -> dict:
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    total = await db.scalar(select(func.count()).select_from(Job))
    fresh = await db.scalar(select(func.count()).select_from(Job).where(Job.created_at > day_ago))
    return {"total": int(total or 0), "added_last_24h": int(fresh or 0)}


async def main() -> int:
    args = parse_args()
    modes = args.mode or list(MODES)

    async with async_session() as db:
        if args.user_id:
            user_id = uuid.UUID(args.user_id)
        else:
            profile = (await db.execute(select(Profile).limit(1))).scalars().first()
            if profile is None:
                print(json.dumps({"ok": False, "error": "no profile to ingest for"}))
                return 1
            user_id = profile.user_id

        before = await _counts(db)
        if args.dry_run:
            print(json.dumps({"ok": True, "dry_run": True, "user_id": str(user_id), "before": before}, indent=1))
            return 0

        # One mode failing does not cancel the rest. A network source going down
        # should cost the day one mode, not the whole ingest -- and the summary
        # says which, rather than the run looking like it succeeded.
        reported: dict[str, object] = {}
        failed = []
        for mode in modes:
            try:
                reported[mode] = await discover_jobs(db, user_id, mode=mode)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                reported[mode] = f"failed: {type(exc).__name__}: {exc}"
                failed.append(mode)

        after = await _counts(db)

    print(json.dumps({
        "ok": not failed,
        "user_id": str(user_id),
        "modes": reported,
        "failed_modes": failed,
        "before": before,
        "after": after,
        "stored": after["total"] - before["total"],
    }, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
