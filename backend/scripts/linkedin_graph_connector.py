#!/usr/bin/env python3
"""Scrape first-degree LinkedIn connections locally and upload them via sync session."""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.linkedin_graph_browser_sync import (  # noqa: E402
    CLICK_SHOW_MORE_SCRIPT,
    LINKEDIN_CONNECTIONS_URL,
    READY_SELECTOR,
    SCROLL_CONNECTIONS_SCRIPT,
    SCRAPE_CONNECTION_CARDS_SCRIPT,
    dedupe_scraped_connections,
)
from app.services.linkedin_graph_service import parse_linkedin_connections_file  # noqa: E402

try:
    from playwright.sync_api import (  # noqa: E402
        BrowserContext,
        Error as PlaywrightError,
        Page,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError:  # pragma: no cover - handled at runtime for local helper usage
    BrowserContext = Page = object  # type: ignore[assignment]
    PlaywrightError = PlaywrightTimeoutError = RuntimeError  # type: ignore[assignment]
    sync_playwright = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read first-degree LinkedIn connections from a logged-in browser and upload "
            "them through NexusReach's sync-session API."
        ),
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Backend base URL, for example http://localhost:8000",
    )
    parser.add_argument(
        "--session-token",
        required=True,
        help="Short-lived session token from /api/linkedin-graph/sync-session",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Batch size to upload per request",
    )
    parser.add_argument(
        "--file",
        help=(
            "Optional fallback: upload a LinkedIn connections CSV or ZIP export instead of "
            "scraping the browser."
        ),
    )
    parser.add_argument(
        "--cdp-url",
        help=(
            "Optional Chrome DevTools endpoint for an already-running logged-in browser, "
            "for example http://127.0.0.1:9222"
        ),
    )
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        choices=["chrome", "msedge", "chromium"],
        help="Browser channel for the local persistent profile mode",
    )
    parser.add_argument(
        "--user-data-dir",
        default="~/.nexusreach/linkedin-graph-browser",
        help="Persistent browser profile directory used when --cdp-url is not provided",
    )
    parser.add_argument(
        "--connections-url",
        default=LINKEDIN_CONNECTIONS_URL,
        help="LinkedIn URL to open for first-degree connections",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser headlessly. Requires an already-authenticated session.",
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=500,
        help="Stop after scraping this many connections",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=120,
        help="Maximum number of scroll iterations on the LinkedIn connections page",
    )
    parser.add_argument(
        "--scroll-pause-ms",
        type=int,
        default=1200,
        help="Wait time after each scroll before collecting more cards",
    )
    parser.add_argument(
        "--login-timeout-seconds",
        type=int,
        default=300,
        help="How long to wait for the user to finish logging into LinkedIn",
    )
    return parser.parse_args()


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def _upload_batches(
    *,
    base_url: str,
    session_token: str,
    connections: list[dict[str, str | None]],
    batch_size: int,
) -> None:
    batch_size = max(1, batch_size)
    with httpx.Client(timeout=60.0) as client:
        for start in range(0, len(connections), batch_size):
            batch = connections[start:start + batch_size]
            is_final_batch = start + batch_size >= len(connections)
            response = client.post(
                f"{base_url.rstrip('/')}/api/linkedin-graph/import-batch",
                json={
                    "session_token": session_token,
                    "connections": batch,
                    "is_final_batch": is_final_batch,
                },
            )
            response.raise_for_status()
            _print_json(response.json())


def _upload_file(
    *,
    base_url: str,
    session_token: str,
    filename: str,
    file_bytes: bytes,
    batch_size: int,
) -> None:
    connections = parse_linkedin_connections_file(filename, file_bytes)
    if not connections:
        raise SystemExit("No connections were found in the provided export.")

    batches = [
        {
            "full_name": row.get("display_name"),
            "linkedin_url": row.get("linkedin_url"),
            "headline": row.get("headline"),
            "current_company_name": row.get("current_company_name"),
            "company_linkedin_url": row.get("company_linkedin_url"),
        }
        for row in connections
    ]
    _upload_batches(
        base_url=base_url,
        session_token=session_token,
        connections=batches,
        batch_size=batch_size,
    )


def _ensure_playwright_available() -> None:
    if sync_playwright is None:
        raise SystemExit(
            "Playwright is not installed for the local connector. "
            "Install it with `pip install playwright` and then run "
            "`python -m playwright install chrome`."
        )


def _looks_like_login(page: Page) -> bool:
    url = page.url.lower()
    if "linkedin.com/login" in url or "linkedin.com/checkpoint/" in url:
        return True
    try:
        body_text = (page.locator("body").text_content(timeout=1000) or "").lower()
    except PlaywrightError:
        return False
    return "sign in" in body_text and "linkedin" in body_text


def _looks_like_security_challenge(page: Page) -> bool:
    url = page.url.lower()
    if "checkpoint/challenge" in url:
        return True
    try:
        body_text = (page.locator("body").text_content(timeout=1000) or "").lower()
    except PlaywrightError:
        return False
    return "security verification" in body_text or "quick security check" in body_text


@contextmanager
def _browser_context(args: argparse.Namespace) -> Iterator[BrowserContext]:
    _ensure_playwright_available()
    assert sync_playwright is not None

    with sync_playwright() as playwright:
        if args.cdp_url:
            browser = playwright.chromium.connect_over_cdp(args.cdp_url)
            if not browser.contexts:
                raise SystemExit(
                    "The CDP browser did not expose any contexts. "
                    "Open Chrome with --remote-debugging-port=9222 and try again."
                )
            yield browser.contexts[0]
            return

        user_data_dir = Path(args.user_data_dir).expanduser().resolve()
        user_data_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs = {
            "user_data_dir": str(user_data_dir),
            "headless": args.headless,
            "viewport": {"width": 1440, "height": 1100},
        }
        if args.browser_channel != "chromium":
            launch_kwargs["channel"] = args.browser_channel

        try:
            context = playwright.chromium.launch_persistent_context(**launch_kwargs)
        except PlaywrightError:
            if args.browser_channel == "chromium":
                raise
            print(
                f"Could not launch channel '{args.browser_channel}'. "
                "Falling back to Playwright Chromium.",
                file=sys.stderr,
            )
            launch_kwargs.pop("channel", None)
            context = playwright.chromium.launch_persistent_context(**launch_kwargs)

        try:
            yield context
        finally:
            context.close()


def _wait_for_connections_page(
    page: Page,
    *,
    headless: bool,
    login_timeout_seconds: int,
) -> None:
    deadline = time.time() + max(5, login_timeout_seconds)
    prompted = False

    while time.time() < deadline:
        try:
            page.wait_for_selector(READY_SELECTOR, timeout=3000)
            return
        except PlaywrightTimeoutError:
            pass

        if _looks_like_login(page):
            if headless:
                raise SystemExit(
                    "LinkedIn is not logged in for this browser session. "
                    "Re-run without --headless or use --cdp-url with an already-authenticated browser."
                )
            if not prompted:
                print(
                    "Log into LinkedIn in the opened browser window. "
                    "The connector will continue automatically once the connections page is ready."
                )
                try:
                    page.bring_to_front()
                except PlaywrightError:
                    pass
                prompted = True
        elif _looks_like_security_challenge(page) and not prompted:
            print(
                "Complete the LinkedIn security challenge in the opened browser window. "
                "The connector will continue automatically once the page loads."
            )
            prompted = True

        page.wait_for_timeout(2000)

    raise SystemExit(
        "Timed out waiting for the LinkedIn connections page to load. "
        "If you are logging in manually, re-run the connector and complete the login faster, "
        "or use --cdp-url with an already logged-in Chrome session."
    )


def _scrape_visible_cards(page: Page) -> list[dict[str, str]]:
    payload = page.evaluate(SCRAPE_CONNECTION_CARDS_SCRIPT)
    return payload if isinstance(payload, list) else []


def _scrape_browser_connections(args: argparse.Namespace) -> list[dict[str, str | None]]:
    with _browser_context(args) as context:
        page = context.new_page()
        try:
            page.goto(args.connections_url, wait_until="domcontentloaded")
            _wait_for_connections_page(
                page,
                headless=args.headless,
                login_timeout_seconds=args.login_timeout_seconds,
            )

            scraped: list[dict[str, str]] = []
            stable_loops = 0
            last_count = 0

            for _ in range(max(1, args.max_scrolls)):
                scraped.extend(_scrape_visible_cards(page))
                deduped = dedupe_scraped_connections(scraped)
                current_count = len(deduped)
                print(f"Scraped {current_count} unique connections so far...")

                if current_count >= max(1, args.max_connections):
                    return deduped[: args.max_connections]

                if current_count == last_count:
                    stable_loops += 1
                else:
                    stable_loops = 0
                last_count = current_count

                clicked_show_more = bool(page.evaluate(CLICK_SHOW_MORE_SCRIPT))
                page.evaluate(SCROLL_CONNECTIONS_SCRIPT)
                page.wait_for_timeout(max(250, args.scroll_pause_ms))

                if stable_loops >= 3 and not clicked_show_more:
                    break

            return dedupe_scraped_connections(scraped)[: args.max_connections]
        finally:
            page.close()


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    if args.file:
        export_path = Path(args.file).expanduser().resolve()
        if not export_path.exists():
            raise SystemExit(f"File not found: {export_path}")
        _upload_file(
            base_url=base_url,
            session_token=args.session_token,
            filename=export_path.name,
            file_bytes=export_path.read_bytes(),
            batch_size=args.batch_size,
        )
        return 0

    connections = _scrape_browser_connections(args)
    if not connections:
        raise SystemExit(
            "No LinkedIn connections were scraped. "
            "LinkedIn may have changed the page structure, or the browser session is not on the connections page."
        )

    _upload_batches(
        base_url=base_url,
        session_token=args.session_token,
        connections=connections,
        batch_size=args.batch_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
