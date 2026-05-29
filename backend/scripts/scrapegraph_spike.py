"""Benchmark NexusReach page retrieval against ScrapeGraphAI.

This is a standalone spike harness, not product integration. Run it from the
backend directory so backend/.env is loaded by app.config:

    cd backend
    SGAI_API_KEY=... python scripts/scrapegraph_spike.py --urls-file urls.txt

Without SGAI_API_KEY or NEXUSREACH_SCRAPEGRAPH_API_KEY, the ScrapeGraph calls
are skipped and the script only records the current NexusReach fetch stack.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Coroutine

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.clients import crawl4ai_client, firecrawl_client, public_page_client
from app.config import settings

SCRAPEGRAPH_API_BASE = "https://v2-api.scrapegraphai.com/api"
BLOCKED_CONTENT_PATTERNS = (
    *public_page_client.INSUFFICIENT_CONTENT_PATTERNS,
    "akamai",
    "powered and protected by",
)

DEFAULT_URLS = [
    "https://www.newgrad-jobs.com/list-software-engineer-jobs",
    "https://www.ventureloop.com/ventureloop/job_search_results.php?pageno=1&btn=1&jcat=12&dc=all&ldata=San%24%24Francisco%2C%24%24CA%2C%24%24US&jt=1&jc=1&jd=1&d=100",
    "https://theorg.com/org/openai",
]

JOB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_job_posting": {"type": ["boolean", "null"]},
        "title": {"type": ["string", "null"]},
        "company_name": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "employment_type": {"type": ["string", "null"]},
        "work_mode": {"type": ["string", "null"]},
        "salary": {"type": ["string", "null"]},
        "posted_at": {"type": ["string", "null"]},
        "application_url": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
    },
    "required": ["is_job_posting", "title", "company_name"],
}

JOB_EXTRACT_PROMPT = (
    "Extract job posting facts explicitly present on the page. "
    "Do not infer missing fields. Return null for absent fields. "
    "Set is_job_posting to false if the page is not a specific job posting."
)


def _summarize_page(page: dict | None, elapsed_ms: int) -> dict:
    if not page:
        return {"ok": False, "elapsed_ms": elapsed_ms}

    content = str(page.get("content") or "")
    html = str(page.get("html") or "")
    markdown = str(page.get("markdown") or "")
    lowered = " ".join([str(page.get("title") or ""), content[:1000], html[:1000]]).lower()
    insufficient_signals = [
        signal
        for signal in BLOCKED_CONTENT_PATTERNS
        if signal in lowered
    ]
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "url": page.get("url"),
        "title": page.get("title"),
        "retrieval_method": page.get("retrieval_method"),
        "fallback_used": bool(page.get("fallback_used")),
        "content_chars": len(content),
        "html_chars": len(html),
        "markdown_chars": len(markdown),
        "insufficient_signals": insufficient_signals,
        "preview": " ".join(content.split())[:300],
    }


async def _timed_page_call(
    call: Callable[[], Coroutine[object, object, dict | None]],
) -> dict:
    started = time.perf_counter()
    try:
        page = await call()
    except Exception as exc:  # noqa: BLE001 - spike harness records failures.
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": f"{type(exc).__name__}: {exc}"}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return _summarize_page(page, elapsed_ms)


def _normalize_result_data(value: object) -> object:
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


async def _call_scrapegraph_scrape(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    url: str,
    timeout_ms: int,
    stealth: bool,
) -> dict:
    payload = {
        "url": url,
        "formats": [{"type": "markdown"}, {"type": "html"}],
        "fetchConfig": {
            "mode": "auto",
            "stealth": stealth,
            "timeout": timeout_ms,
        },
    }
    headers = {"SGAI-APIKEY": api_key, "Content-Type": "application/json"}
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{SCRAPEGRAPH_API_BASE}/scrape",
            json=payload,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(exc)}

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "status_code": response.status_code,
            "error": response.text[:500],
        }

    data = response.json()
    results = data.get("results") or {}
    markdown = _normalize_result_data((results.get("markdown") or {}).get("data"))
    html = _normalize_result_data((results.get("html") or {}).get("data"))
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "id": data.get("id"),
        "content_type": (data.get("metadata") or {}).get("contentType"),
        "markdown_chars": len(markdown or "") if isinstance(markdown, str) else 0,
        "html_chars": len(html or "") if isinstance(html, str) else 0,
        "markdown_preview": " ".join(str(markdown or "").split())[:300],
    }


async def _call_scrapegraph_extract(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    url: str,
    timeout_ms: int,
    stealth: bool,
) -> dict:
    payload = {
        "url": url,
        "prompt": JOB_EXTRACT_PROMPT,
        "schema": JOB_EXTRACT_SCHEMA,
        "fetchConfig": {
            "mode": "auto",
            "stealth": stealth,
            "timeout": timeout_ms,
        },
    }
    headers = {"SGAI-APIKEY": api_key, "Content-Type": "application/json"}
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{SCRAPEGRAPH_API_BASE}/extract",
            json=payload,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "error": str(exc)}

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "status_code": response.status_code,
            "error": response.text[:500],
        }

    data = response.json()
    extracted = data.get("json") or {}
    has_required_job_fields = bool(
        extracted.get("is_job_posting")
        and extracted.get("title")
        and extracted.get("company_name")
    )
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "id": data.get("id"),
        "json": extracted,
        "has_required_job_fields": has_required_job_fields,
        "usage": data.get("usage"),
        "fetch_metadata": (data.get("metadata") or {}).get("fetch"),
    }


def _read_urls(args: argparse.Namespace) -> list[str]:
    urls: list[str] = []
    if args.urls_file:
        urls.extend(
            line.strip()
            for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    urls.extend(args.urls or [])
    if not urls:
        urls = DEFAULT_URLS.copy()

    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)
        if len(unique_urls) >= args.limit:
            break
    return unique_urls


def _skip_result(reason: str) -> dict:
    return {"ok": False, "skipped": True, "reason": reason}


async def _run(args: argparse.Namespace) -> dict:
    urls = _read_urls(args)
    api_key = (
        os.getenv("SGAI_API_KEY")
        or os.getenv("NEXUSREACH_SCRAPEGRAPH_API_KEY")
        or settings.scrapegraph_api_key
        or ""
    )
    timeout_ms = int(args.timeout_seconds * 1000)

    output = {
        "scrapegraph_configured": bool(api_key),
        "scrapegraph_stealth": args.stealth,
        "urls": [],
    }

    async with httpx.AsyncClient(timeout=args.timeout_seconds + 10) as client:
        for url in urls:
            row = {
                "url": url,
                "current_stack": {
                    "direct": await _timed_page_call(
                        lambda url=url: public_page_client.fetch_direct_page(
                            url,
                            timeout_seconds=args.timeout_seconds,
                        )
                    ),
                    "crawl4ai": await _timed_page_call(
                        lambda url=url: crawl4ai_client.fetch_url(
                            url,
                            timeout_seconds=args.timeout_seconds,
                        )
                    ),
                    "firecrawl": await _timed_page_call(
                        lambda url=url: firecrawl_client.scrape_url(
                            url,
                            timeout_seconds=args.timeout_seconds,
                        )
                    ),
                    "selected": await _timed_page_call(
                        lambda url=url: public_page_client.fetch_page(
                            url,
                            timeout_seconds=args.timeout_seconds,
                        )
                    ),
                },
                "scrapegraph": {
                    "scrape": _skip_result("missing SGAI_API_KEY")
                    if not api_key
                    else await _call_scrapegraph_scrape(
                        client,
                        api_key=api_key,
                        url=url,
                        timeout_ms=timeout_ms,
                        stealth=args.stealth,
                    ),
                    "extract": _skip_result(
                        "skip_extract enabled" if args.skip_extract else "missing SGAI_API_KEY"
                    )
                    if not api_key or args.skip_extract
                    else await _call_scrapegraph_extract(
                        client,
                        api_key=api_key,
                        url=url,
                        timeout_ms=timeout_ms,
                        stealth=args.stealth,
                    ),
                },
            }
            output["urls"].append(row)

    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", help="URLs to benchmark.")
    parser.add_argument("--urls-file", help="File with one URL per line.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument("--stealth", action="store_true", help="Use ScrapeGraph stealth mode.")
    parser.add_argument("--skip-extract", action="store_true", help="Skip ScrapeGraph extract calls.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = asyncio.run(_run(args))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
