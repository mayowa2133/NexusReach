"""Deterministic safety checks for AI-generated outbound messages."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_URL_RE = re.compile(r"https?://[^\s<>\]\[\)\(\"']+", re.IGNORECASE)
_HTML_RE = re.compile(r"<\s*(?:script|iframe|form|object|embed|img|svg|a)\b", re.IGNORECASE)
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|system|developer)\s+instructions", re.I),
    re.compile(r"(?:reveal|print|send|exfiltrate).{0,40}(?:secret|token|password|api[ _-]?key)", re.I),
    re.compile(r"(?:system|developer)\s+prompt", re.I),
    re.compile(r"you\s+are\s+(?:chatgpt|an?\s+ai|the\s+assistant)", re.I),
)
_CREDENTIAL_REQUEST_RE = re.compile(
    r"(?:send|share|provide|reply\s+with).{0,50}(?:password|verification\s+code|one[- ]time\s+code|api[ _-]?key|access\s+token|secret)",
    re.I,
)
_BIDI_OR_ZERO_WIDTH_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")


def detect_untrusted_prompt_injection(*values: str | None) -> list[str]:
    combined = "\n".join(value or "" for value in values)[:100_000]
    reasons: list[str] = []
    if any(pattern.search(combined) for pattern in _INJECTION_PATTERNS):
        reasons.append("untrusted_context_contains_instruction_like_text")
    if _HTML_RE.search(combined):
        reasons.append("untrusted_context_contains_active_markup")
    return reasons


def _normalize_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.rstrip(".,;:!?"))
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), f"{parsed.hostname.lower()}{port}", path, "", ""))


def assess_generated_message_safety(
    *,
    subject: str | None,
    body: str,
    trusted_urls: list[str | None],
    input_risk_reasons: list[str] | None = None,
) -> dict:
    reasons = list(input_risk_reasons or [])
    content = f"{subject or ''}\n{body or ''}"
    allowed = {_normalize_url(url) for url in trusted_urls if url}
    allowed.discard(None)
    for match in _URL_RE.findall(content):
        normalized = _normalize_url(match)
        if not normalized or normalized not in allowed:
            reasons.append("generated_message_contains_unapproved_url")
            break
    if _CREDENTIAL_REQUEST_RE.search(content):
        reasons.append("generated_message_requests_sensitive_credentials")
    if _HTML_RE.search(content):
        reasons.append("generated_message_contains_active_markup")
    if _BIDI_OR_ZERO_WIDTH_RE.search(content):
        reasons.append("generated_message_contains_invisible_directional_text")
    if "\r" in (subject or "") or "\n" in (subject or ""):
        reasons.append("generated_subject_contains_header_control_characters")
    if len(content) > 5_000:
        reasons.append("generated_message_exceeds_safe_length")
    deduped = list(dict.fromkeys(reasons))
    return {
        "safe_for_automatic_send": not deduped,
        "requires_human_review": bool(deduped),
        "reasons": deduped,
        "policy_version": "2026-07-11.1",
    }
