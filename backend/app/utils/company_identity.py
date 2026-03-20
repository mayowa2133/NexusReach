"""Helpers for canonicalizing company identity and domain trust."""

from __future__ import annotations

import re
from urllib.parse import urlparse

LEGAL_SUFFIX_TOKENS = {
    "co",
    "company",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "llc",
    "plc",
    "gmbh",
    "ag",
    "pte",
    "pty",
}
LEADING_STOP_TOKENS = {"the"}


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def normalize_company_name(value: str | None) -> str:
    tokens = _tokens(value)
    filtered = [token for token in tokens if token not in LEGAL_SUFFIX_TOKENS]
    while filtered and filtered[0] in LEADING_STOP_TOKENS:
        filtered = filtered[1:]
    canonical = filtered or tokens
    return " ".join(canonical)


def canonical_company_display_name(value: str | None) -> str:
    stripped = " ".join((value or "").split()).strip()
    if not stripped:
        return ""
    if stripped.islower():
        return " ".join(token.capitalize() for token in stripped.split())
    return stripped


def is_ambiguous_company_name(value: str | None) -> bool:
    normalized = normalize_company_name(value)
    if not normalized:
        return False
    tokens = normalized.split()
    return len(tokens) == 1 and len(tokens[0]) <= 4


def domain_root(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    host = urlparse(raw if "://" in raw else f"https://{raw}").netloc.lower()
    if not host:
        host = raw.split("/")[0]
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "org", "net"}:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def should_trust_company_enrichment(
    requested_name: str,
    *,
    resolved_name: str | None = None,
    domain: str | None = None,
) -> bool:
    requested_normalized = normalize_company_name(requested_name)
    if not requested_normalized:
        return False

    resolved_normalized = normalize_company_name(resolved_name or requested_name)
    if requested_normalized != resolved_normalized:
        return False

    if not domain:
        return False

    if is_ambiguous_company_name(requested_name):
        return False

    return normalize_company_name(domain_root(domain)) == requested_normalized
