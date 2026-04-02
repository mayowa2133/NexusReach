#!/usr/bin/env python3
"""Upload a local LinkedIn connections export through a sync session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from app.services.linkedin_graph_service import parse_linkedin_connections_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a LinkedIn connections CSV or ZIP through NexusReach's sync-session API.",
    )
    parser.add_argument("--base-url", required=True, help="Backend base URL, for example http://localhost:8000")
    parser.add_argument("--session-token", required=True, help="Short-lived session token from /api/linkedin-graph/sync-session")
    parser.add_argument("--file", required=True, help="Path to a LinkedIn connections CSV or ZIP export")
    parser.add_argument("--batch-size", type=int, default=250, help="Batch size to upload per request")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    export_path = Path(args.file).expanduser().resolve()
    if not export_path.exists():
        raise SystemExit(f"File not found: {export_path}")

    connections = parse_linkedin_connections_file(export_path.name, export_path.read_bytes())
    if not connections:
        raise SystemExit("No connections were found in the provided export.")

    batch_size = max(1, args.batch_size)
    base_url = args.base_url.rstrip("/")
    with httpx.Client(timeout=60.0) as client:
        for start in range(0, len(connections), batch_size):
            batch = connections[start:start + batch_size]
            is_final_batch = start + batch_size >= len(connections)
            response = client.post(
                f"{base_url}/api/linkedin-graph/import-batch",
                json={
                    "session_token": args.session_token,
                    "connections": batch,
                    "is_final_batch": is_final_batch,
                },
            )
            response.raise_for_status()
            payload = response.json()
            print(json.dumps(payload, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
