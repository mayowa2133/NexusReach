"""Evidence ledger and fail-closed truthfulness validation for resume artifacts."""

from __future__ import annotations

import re
from typing import Any

from app.services.resume_artifact.textnorm import _clean, _latex_plain_text


TRUTHFULNESS_LEDGER_VERSION = 1

_REGULATED_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CPA", re.compile(r"\bCPA\b", re.I)),
    ("RN license", re.compile(r"\b(?:RN|registered nurse)\s+(?:license|licen[cs]ure|registration)\b", re.I)),
    ("bar admission", re.compile(r"\b(?:bar admission|admitted to (?:the )?bar|licensed attorney)\b", re.I)),
    ("security clearance", re.compile(r"\b(?:(?:top )?secret|security) clearance\b", re.I)),
    ("PMP", re.compile(r"\bPMP\b", re.I)),
    ("CISSP", re.compile(r"\bCISSP\b", re.I)),
    ("driver's license", re.compile(r"\bdriver'?s? licen[cs]e\b", re.I)),
)


def _source_evidence(parsed: dict[str, Any]) -> tuple[str, list[dict]]:
    text_parts: list[str] = []
    entries: list[dict] = []
    for section in ("experience", "projects", "education"):
        for index, item in enumerate(parsed.get(section) or []):
            if not isinstance(item, dict):
                continue
            identity = _clean(
                item.get("company")
                or item.get("name")
                or item.get("institution")
                or item.get("title")
            )
            if identity:
                text_parts.append(identity)
                entries.append({
                    "evidence_id": f"{section}:{index}:identity",
                    "kind": "source",
                    "text": identity,
                })
            for bullet_index, bullet in enumerate(item.get("bullets") or []):
                cleaned = _clean(bullet)
                if cleaned:
                    text_parts.append(cleaned)
                    entries.append({
                        "evidence_id": f"{section}:{index}:bullet:{bullet_index}",
                        "kind": "source",
                        "text": cleaned,
                    })
            for key in ("description", "degree", "field"):
                cleaned = _clean(item.get(key))
                if cleaned:
                    text_parts.append(cleaned)
    for index, skill in enumerate(parsed.get("skills") or []):
        cleaned = _clean(skill)
        if cleaned:
            text_parts.append(cleaned)
            entries.append({
                "evidence_id": f"skill:{index}",
                "kind": "source",
                "text": cleaned,
            })
    for category, values in (parsed.get("skills_by_category") or {}).items():
        for index, skill in enumerate(values if isinstance(values, list) else []):
            cleaned = _clean(skill)
            if cleaned:
                text_parts.append(cleaned)
                entries.append({
                    "evidence_id": f"skill_category:{category}:{index}",
                    "kind": "source",
                    "text": cleaned,
                })
    for index, certificate in enumerate(parsed.get("certificates") or []):
        cleaned = _clean(certificate)
        if cleaned:
            text_parts.append(cleaned)
            entries.append({
                "evidence_id": f"certificate:{index}",
                "kind": "source",
                "text": cleaned,
            })
    return "\n".join(text_parts), entries


def _term_supported(term: str, source_text: str) -> bool:
    cleaned = _clean(term)
    if not cleaned:
        return False
    escaped = re.escape(cleaned).replace(r"\ ", r"\s+")
    return bool(re.search(
        rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
        source_text,
        re.I,
    ))


def build_truthfulness_ledger(
    *,
    parsed: dict[str, Any],
    content: str,
    tailored: object,
    rewrite_decisions: dict[str, str] | None = None,
    auto_accept_inferred: bool = False,
) -> dict:
    """Build evidence links and reject any rendered unsupported generated claim."""
    source_text, source_entries = _source_evidence(parsed)
    rendered_text = _latex_plain_text(content)
    decisions = rewrite_decisions or {}
    ledger_entries: list[dict] = []
    violations: list[dict] = []

    for entry in source_entries:
        if _clean(entry["text"]).casefold() in rendered_text.casefold():
            ledger_entries.append({**entry, "rendered": True, "verified": True})

    suggestion_fields = (
        "skills_to_emphasize",
        "skills_to_add",
        "keywords_to_add",
    )
    for field in suggestion_fields:
        for index, term in enumerate(getattr(tailored, field, None) or []):
            cleaned = _clean(term)
            if not cleaned or not _term_supported(cleaned, rendered_text):
                continue
            supported = _term_supported(cleaned, source_text)
            entry = {
                "evidence_id": f"generated:{field}:{index}",
                "kind": "generated_term",
                "field": field,
                "text": cleaned,
                "source_supported": supported,
                "verified": supported,
            }
            ledger_entries.append(entry)
            if not supported:
                violations.append({
                    "type": "unsupported_generated_term",
                    "field": field,
                    "text": cleaned,
                })

    for index, rewrite in enumerate(getattr(tailored, "bullet_rewrites", None) or []):
        if not isinstance(rewrite, dict):
            continue
        rewritten = _clean(rewrite.get("rewritten"))
        if not rewritten or rewritten.casefold() not in rendered_text.casefold():
            continue
        rewrite_id = _clean(rewrite.get("id")) or f"rewrite:{index}"
        inferred = (
            rewrite.get("change_type") == "inferred_claim"
            or bool(rewrite.get("requires_user_confirm"))
        )
        accepted = decisions.get(rewrite_id) == "accepted" or (
            inferred and auto_accept_inferred
        )
        verified = not inferred or accepted
        ledger_entries.append({
            "evidence_id": rewrite_id,
            "kind": "rewrite",
            "text": rewritten,
            "source_evidence": _clean(rewrite.get("original")),
            "change_type": rewrite.get("change_type"),
            "explicit_acceptance": accepted,
            "verified": verified,
        })
        if not verified:
            violations.append({
                "type": "unaccepted_inferred_rewrite",
                "rewrite_id": rewrite_id,
                "text": rewritten,
            })

    accepted_rewrite_text = "\n".join(
        str(entry.get("text") or "")
        for entry in ledger_entries
        if entry.get("kind") == "rewrite" and entry.get("explicit_acceptance")
    )
    for label, pattern in _REGULATED_CLAIM_PATTERNS:
        if not pattern.search(rendered_text):
            continue
        if pattern.search(source_text) or pattern.search(accepted_rewrite_text):
            ledger_entries.append({
                "evidence_id": f"regulated:{label.lower().replace(' ', '_')}",
                "kind": "regulated_claim",
                "text": label,
                "verified": True,
            })
        else:
            violations.append({
                "type": "unsupported_regulated_claim",
                "text": label,
            })

    return {
        "version": TRUTHFULNESS_LEDGER_VERSION,
        "status": "passed" if not violations else "failed",
        "entries": ledger_entries,
        "violations": violations,
        "rendered_entry_count": len(ledger_entries),
    }


def validate_truthfulness_ledger(ledger: dict) -> None:
    if ledger.get("status") != "passed" or ledger.get("violations"):
        labels = ", ".join(
            str(item.get("text") or item.get("type") or "unknown")
            for item in ledger.get("violations") or []
        )
        raise ValueError(
            "Resume artifact contains unsupported or unaccepted claims"
            + (f": {labels}" if labels else ".")
        )
