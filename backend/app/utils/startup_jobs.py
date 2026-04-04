"""Helpers for startup-source job discovery, tagging, and link resolution."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.clients import ats_client

STARTUP_TAG = "startup"
STARTUP_SOURCE_PREFIX = "startup_source:"
STARTUP_DISCOVER_FALLBACK_QUERIES = [
    "Founding Engineer",
    "Software Engineer",
    "Full Stack Engineer",
    "Product Engineer",
    "ML Engineer",
    "Product Designer",
    "Product Manager",
    "Growth",
]
STARTUP_CAREERS_HINTS = (
    "careers",
    "career",
    "jobs",
    "job",
    "join",
    "join-us",
    "team",
    "work-with-us",
    "open-roles",
    "openings",
    "positions",
)
_NON_EXACT_TERMINALS = {
    "jobs",
    "job",
    "careers",
    "career",
    "join",
    "join-us",
    "team",
    "about",
    "company",
    "people",
    "positions",
    "open-positions",
    "openings",
    "roles",
    "work-with-us",
}
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_EXACT_PATH_RE = re.compile(r"/(job|jobs|role|roles|position|positions|opening|openings)/[^/?#]+", re.IGNORECASE)


def startup_source_tag(source_key: str) -> str:
    return f"{STARTUP_SOURCE_PREFIX}{source_key}"


def startup_tags(source_key: str) -> list[str]:
    return [STARTUP_TAG, startup_source_tag(source_key)]


def is_startup_tag(tag: str | None) -> bool:
    return bool(tag) and (tag == STARTUP_TAG or tag.startswith(STARTUP_SOURCE_PREFIX))


def has_startup_tag(tags: list[str] | None) -> bool:
    return any(is_startup_tag(tag) for tag in tags or [])


def merge_startup_tags(existing_tags: list[str] | None, incoming_tags: list[str] | None) -> list[str] | None:
    current = list(existing_tags or [])
    if not incoming_tags:
        return current or None
    if not current:
        unique_incoming = list(dict.fromkeys(incoming_tags))
        return unique_incoming or None
    for tag in incoming_tags:
        if is_startup_tag(tag) and tag not in current:
            current.append(tag)
    return current or None


def merge_tags(existing_tags: list[str] | None, incoming_tags: list[str] | None) -> list[str] | None:
    merged = list(existing_tags or [])
    for tag in incoming_tags or []:
        if tag not in merged:
            merged.append(tag)
    return merged or None


def append_startup_tags(data: dict, source_key: str) -> dict:
    return {
        **data,
        "tags": merge_tags(data.get("tags"), startup_tags(source_key)),
    }


def startup_discover_queries(target_roles: list[str] | None) -> list[str]:
    candidates = target_roles or STARTUP_DISCOVER_FALLBACK_QUERIES
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def query_tokens(query: str) -> list[str]:
    return [token for token in _QUERY_TOKEN_RE.findall((query or "").lower()) if len(token) >= 2]


def text_matches_query(*, text: str, query: str) -> bool:
    normalized_query = " ".join(query_tokens(query))
    if not normalized_query:
        return True

    haystack = " ".join(query_tokens(text))
    if not haystack:
        return False
    if normalized_query in haystack:
        return True

    tokens = normalized_query.split()
    hits = sum(1 for token in tokens if token in haystack)
    required = len(tokens) if len(tokens) <= 2 else max(2, len(tokens) - 1)
    return hits >= required


def job_matches_any_query(job_data: dict, queries: list[str]) -> bool:
    if not queries:
        return True
    parts = [
        job_data.get("title"),
        job_data.get("company_name"),
        job_data.get("location"),
        job_data.get("description"),
        job_data.get("department"),
        " ".join(str(tag) for tag in (job_data.get("tags") or [])),
    ]
    haystack = " ".join(str(part or "") for part in parts if part)
    return any(text_matches_query(text=haystack, query=query) for query in queries)


def looks_like_careers_page(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    return any(hint in path for hint in STARTUP_CAREERS_HINTS) or host.startswith("jobs.")


def is_exactish_generic_job_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    if not path or not _EXACT_PATH_RE.search(path):
        return False
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return False
    terminal = parts[-1]
    return terminal not in _NON_EXACT_TERMINALS


def is_supported_job_link(url: str) -> bool:
    parsed = ats_client.parse_ats_job_url(url)
    if not parsed:
        return False
    if parsed.ats_type != "generic_exact":
        return True
    return is_exactish_generic_job_url(url)


def extract_candidate_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    links: dict[str, int] = {}

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue

        score = 0
        if is_supported_job_link(absolute):
            score = 100
        elif looks_like_careers_page(absolute):
            score = 20

        if score <= 0:
            continue
        links[absolute] = max(links.get(absolute, 0), score)

    return [url for url, _score in sorted(links.items(), key=lambda item: (-item[1], item[0]))]
