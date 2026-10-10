"""Generic HTML/text/URL parsing utilities for ATS pages."""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urlparse

from app.utils import html_parsing



# A "datePosted" value embedded in any inline JSON blob (__NEXT_DATA__, Apollo
# state, partial JSON-LD the strict parser rejected). Tolerates a leading
# backslash so it also matches inside double-encoded JSON strings.
DATE_POSTED_JSON_RE = re.compile(r'\\?"datePosted\\?"\s*:\s*\\?"([^"\\]+)\\?"', re.IGNORECASE)

# A microdata <meta itemprop="datePosted" content="..."> or
# <time itemprop="datePosted" datetime="..."> tag.

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
    return html_parsing.text(value or "")

def _normalize_text(value: str | None) -> str:
    normalized = unescape(value or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()

def _extract_title(html: str) -> str:
    return html_parsing.element_text(html or "", "title")

def _extract_heading(html: str) -> str:
    return html_parsing.element_text(html or "", "h1")

def _find_attr(tag: str, attr: str) -> str:
    match = re.search(rf'{attr}\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""

def _extract_meta_content(html: str, key: str) -> str:
    lowered_key = key.lower()
    root = html_parsing.document(html or "")
    if root is None:
        return ""
    for tag in root.iter("meta"):
        name = tag.get("name", "") or tag.get("property", "")
        if name.lower() != lowered_key:
            continue
        content = tag.get("content", "")
        if content:
            return content
    return ""

def _extract_posted_at(html: str) -> str | None:
    """Best-effort posting date from an HTML page when JSON-LD parsing failed.

    Mines, in priority order: an inline ``"datePosted"`` JSON value (covers
    ``__NEXT_DATA__`` / Apollo state / JSON-LD the strict parser rejected), a
    microdata ``itemprop="datePosted"`` meta/time tag, then the
    ``article:published_time`` meta tag. Returns the raw date string (an ISO
    datetime or date, which the ingest parser resolves) or None. The HTML
    fallbacks otherwise emit no date and the job would order by ingest time.
    """
    if not html:
        return None

    json_match = DATE_POSTED_JSON_RE.search(html)
    if json_match and json_match.group(1).strip():
        return json_match.group(1).strip()

    root = html_parsing.document(html)
    if root is not None:
        for tag in root.iter("meta", "time"):
            if (tag.get("itemprop") or "").lower() == "dateposted":
                value = tag.get("content") or tag.get("datetime")
                if value:
                    return value

    published = _extract_meta_content(html, "article:published_time")
    if published.strip():
        return published.strip()

    return None

def _extract_canonical_link(html: str) -> str | None:
    root = html_parsing.document(html or "")
    if root is not None:
        for tag in root.iter("link"):
            if "canonical" in (tag.get("rel") or "").lower().split():
                href = (tag.get("href") or "").strip()
                if href:
                    return _clean_url(href)
    return None

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
    pending = [payload]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            payload_type = item.get("@type")
            if payload_type == "JobPosting" or (
                isinstance(payload_type, list) and "JobPosting" in payload_type
            ):
                candidates.append(item)
            if isinstance(item.get("@graph"), list):
                pending.extend(reversed(item["@graph"]))
        elif isinstance(item, list):
            pending.extend(reversed(item))
    return candidates

def _extract_json_ld_job(html: str) -> dict | None:
    root = html_parsing.document(html or "")
    if root is None:
        return None
    for tag in root.iter("script"):
        if (tag.get("type") or "").lower() != "application/ld+json":
            continue
        raw_payload = (tag.text or "").strip()
        if not raw_payload:
            continue
        try:
            payload = json.loads(raw_payload)
        except (ValueError, RecursionError):
            continue
        candidates = _job_posting_candidates(payload)
        if candidates:
            return candidates[0]
    return None

def _extract_static_router_payload(html: str) -> dict | None:
    # Tokenize the assignment once; repeated unterminated strings must not make
    # a lazy regex rescan the remaining page for every candidate.
    start = (html or "").find("window.__staticRouterHydrationData")
    if start < 0:
        return None
    rest = html[start + len("window.__staticRouterHydrationData"):].lstrip()
    if not rest.startswith("="):
        return None
    rest = rest[1:].lstrip()
    if not rest.startswith("JSON.parse("):
        return None
    try:
        decoded, _ = json.JSONDecoder().raw_decode(rest[len("JSON.parse("):].lstrip())
        payload = json.loads(decoded)
    except (ValueError, TypeError, RecursionError):
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
