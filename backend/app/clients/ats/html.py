"""Generic HTML/text/URL parsing utilities for ATS pages."""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urlparse




JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(?P<payload>.*?)</script>",
    flags=re.IGNORECASE | re.DOTALL,
)


STATIC_ROUTER_RE = re.compile(
    r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\(\"(?P<payload>.*?)\"\);",
    flags=re.DOTALL,
)


TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", flags=re.IGNORECASE | re.DOTALL)


HEADING_RE = re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", flags=re.IGNORECASE | re.DOTALL)


CANONICAL_LINK_RE = re.compile(
    r"<link\b[^>]*rel=[\"']canonical[\"'][^>]*href=[\"'](?P<href>[^\"']+)[\"']",
    flags=re.IGNORECASE,
)


TAG_RE = re.compile(r"<[^>]+>")


WHITESPACE_RE = re.compile(r"\s+")


COMMON_SUBDOMAINS = {"jobs", "careers", "apply", "app", "www"}


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return parsed._replace(path=path, query="", fragment="").geturl()


def _humanize_company_slug(slug: str) -> str:
    """Turn an ATS board slug into a readable company name (audit M2).

    e.g. "match-group" -> "Match Group", "spotify" -> "Spotify". Concatenated
    single-token slugs are simply capitalized (best effort without a lookup).
    """
    cleaned = (slug or "").replace("-", " ").replace("_", " ").strip()
    if not cleaned:
        return slug or ""
    return " ".join(word[:1].upper() + word[1:] for word in cleaned.split())


def _strip_tags(value: str | None) -> str:
    return WHITESPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", value or ""))).strip()


def _normalize_text(value: str | None) -> str:
    normalized = unescape(value or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _extract_title(html: str) -> str:
    match = TITLE_RE.search(html or "")
    return _strip_tags(match.group("title")) if match else ""


def _extract_heading(html: str) -> str:
    match = HEADING_RE.search(html or "")
    return _strip_tags(match.group("title")) if match else ""


def _find_attr(tag: str, attr: str) -> str:
    match = re.search(rf'{attr}\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""


def _extract_meta_content(html: str, key: str) -> str:
    lowered_key = key.lower()
    for match in re.finditer(r"<meta\b[^>]*>", html or "", flags=re.IGNORECASE):
        tag = match.group(0)
        name = _find_attr(tag, "name") or _find_attr(tag, "property")
        if name.lower() != lowered_key:
            continue
        content = _find_attr(tag, "content")
        if content:
            return content
    return ""


def _extract_canonical_link(html: str) -> str | None:
    match = CANONICAL_LINK_RE.search(html or "")
    if not match:
        return None
    href = unescape(match.group("href")).strip()
    if not href:
        return None
    return _clean_url(href)


def _domain_root(host: str | None) -> str:
    parts = [part for part in (host or "").lower().split(".") if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts[-1]) == 2 and len(parts) >= 3:
        return parts[-3]
    return parts[-2]


def _host_ats_label(host: str) -> str:
    root = _domain_root(host)
    label = re.sub(r"[^a-z0-9]+", "_", root).strip("_")
    return f"{label}_jobs" if label else "custom_jobs"


def _display_company_slug(company_slug: str | None, *, raw_name: str | None = None) -> str:
    if not company_slug:
        return ""

    normalized_slug = company_slug.replace("-", " ").strip()
    if raw_name:
        pattern = r"[-\s]+".join(re.escape(part) for part in normalized_slug.split() if part)
        if pattern:
            match = re.search(rf"\b{pattern}\b", raw_name, flags=re.IGNORECASE)
            if match:
                return match.group(0).replace("-", " ")

    return " ".join(part.capitalize() for part in normalized_slug.split())


def _job_posting_candidates(payload: object) -> list[dict]:
    candidates: list[dict] = []
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type == "JobPosting" or (
            isinstance(payload_type, list) and "JobPosting" in payload_type
        ):
            candidates.append(payload)
        if isinstance(payload.get("@graph"), list):
            for item in payload["@graph"]:
                candidates.extend(_job_posting_candidates(item))
    elif isinstance(payload, list):
        for item in payload:
            candidates.extend(_job_posting_candidates(item))
    return candidates


def _extract_json_ld_job(html: str) -> dict | None:
    for match in JSON_LD_RE.finditer(html or ""):
        raw_payload = match.group("payload").strip()
        if not raw_payload:
            continue
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue
        candidates = _job_posting_candidates(payload)
        if candidates:
            return candidates[0]
    return None


def _extract_static_router_payload(html: str) -> dict | None:
    match = STATIC_ROUTER_RE.search(html or "")
    if not match:
        return None
    try:
        decoded = json.loads(f"\"{match.group('payload')}\"")
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_posted_at(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _epoch_ms_to_iso(value: object) -> str | None:
    """Convert a Unix epoch-millisecond timestamp to an ISO 8601 string."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return None


def _json_ld_company(job_posting: dict, host: str) -> str:
    hiring = job_posting.get("hiringOrganization")
    if isinstance(hiring, dict):
        name = hiring.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return _domain_root(host).title()


def _json_ld_location(job_posting: dict) -> str | None:
    raw_locations = job_posting.get("jobLocation")
    if not raw_locations:
        return None

    if not isinstance(raw_locations, list):
        raw_locations = [raw_locations]

    formatted: list[str] = []
    for location in raw_locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            joined = ", ".join(str(part).strip() for part in parts if str(part).strip())
            if joined:
                formatted.append(joined)
    return " | ".join(dict.fromkeys(formatted)) or None


WORKDAY_JOB_TOKEN_RE = re.compile(r"_(?P<token>JR[A-Za-z0-9-]+)$")


def _workday_company_slug(host: str) -> str | None:
    host_parts = [part for part in (host or "").lower().split(".") if part]
    if len(host_parts) >= 4 and host_parts[-2:] == ["myworkdayjobs", "com"]:
        return host_parts[0]
    return _domain_root(host) or None
