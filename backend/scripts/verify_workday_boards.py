#!/usr/bin/env python3
"""Verify curated Workday board configs against the live jobs API.

Workday tenants drift (the ``wd`` tier or site name changes), and a drifted
config silently returns nothing. Run this to find dead entries and get
paste-ready repaired config lines for app/clients/workday_client.py.

Usage:
  python scripts/verify_workday_boards.py              # tech + non-tech
  python scripts/verify_workday_boards.py --nontech    # non-tech only
  python scripts/verify_workday_boards.py --tech       # tech only
  python scripts/verify_workday_boards.py --no-repair  # skip tier auto-repair

Exit code is non-zero if any config is dead (no tier returns jobs), so this
doubles as an ops gate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.clients import workday_client  # noqa: E402


def _format_entry(r: dict) -> str:
    vert = f', "vertical": "{r["vertical"]}"' if r.get("vertical") else ""
    return (
        f'    {{"label": "{r["label"]}", "company": "{r["company"]}", '
        f'"wd": "{r["wd"]}", "site": "{r["site"]}"{vert}}},  # total={r.get("total", 0)}'
    )


async def _run(args: argparse.Namespace) -> int:
    if args.nontech:
        registry = list(workday_client.WORKDAY_NONTECH_COMPANIES)
    elif args.tech:
        registry = list(workday_client.WORKDAY_COMPANIES)
    else:
        registry = [*workday_client.WORKDAY_COMPANIES, *workday_client.WORKDAY_NONTECH_COMPANIES]

    results = await workday_client.verify_all_workday(registry, repair=not args.no_repair)

    ok = [r for r in results if r["status"] == "ok"]
    repaired = [r for r in results if r["status"] == "repaired"]
    dead = [r for r in results if r["status"] == "dead"]

    print(f"\n✅ OK: {len(ok)}   🔧 REPAIRABLE: {len(repaired)}   ❌ DEAD: {len(dead)}\n")

    if repaired:
        print("🔧 DRIFTED — configured tier dead, replace with these working configs:")
        for r in sorted(repaired, key=lambda x: x["label"]):
            print(f"   {r['label']}: {r['old_wd']} -> {r['wd']}")
            print(_format_entry(r))
        print()

    if dead:
        print("❌ DEAD — no tier returns jobs; investigate site name or remove:")
        for r in sorted(dead, key=lambda x: x["label"]):
            print(f"   {r['label']} ({r['company']}/{r['wd']}/{r['site']})")
        print()

    # non-zero exit if anything is unrecoverable
    return 1 if dead else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nontech", action="store_true", help="non-tech registry only")
    parser.add_argument("--tech", action="store_true", help="tech registry only")
    parser.add_argument("--no-repair", action="store_true", help="skip wd-tier auto-repair")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
