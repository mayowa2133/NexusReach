"""Minimal deployed-environment smoke checks.

Run after a production or staging deploy:

    NEXUSREACH_API_URL=https://api.example.com python scripts/production_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _request_json(url: str, token: str | None = None) -> tuple[int, dict[str, object]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body}
        return exc.code, payload
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def main() -> int:
    api_url = os.environ.get("NEXUSREACH_API_URL", "").rstrip("/")
    if not api_url:
        print("NEXUSREACH_API_URL is required", file=sys.stderr)
        return 2

    health_status, health = _request_json(f"{api_url}/api/health")
    print(f"health_status={health_status} payload={health}")
    if health_status != 200 or health.get("status") != "ok":
        return 1

    token = os.environ.get("NEXUSREACH_SMOKE_BEARER_TOKEN")
    if token:
        auth_status, auth_payload = _request_json(f"{api_url}/api/auth/me", token)
        print(f"auth_status={auth_status} payload={auth_payload}")
        if auth_status != 200:
            return 1
    else:
        print("auth smoke skipped: NEXUSREACH_SMOKE_BEARER_TOKEN is not set")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
