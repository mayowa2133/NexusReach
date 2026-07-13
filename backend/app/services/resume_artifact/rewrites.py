"""Bullet rewrite application and accept/reject decision filtering."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any


from app.services.resume_artifact.textnorm import _BULLET_MARKER_RE, _clean, _metric_tokens, _normalize_bullet_text

logger = logging.getLogger(__name__)


def _should_use_rewrite(original: str, rewrite: str, *, change_type: str = "reframe") -> bool:
    original_tokens = _metric_tokens(original)
    rewrite_tokens = _metric_tokens(rewrite)
    # Every concrete metric in the source is evidence and must survive every
    # rewrite type. Adding an inferred claim is not permission to discard a
    # percentage, count, currency amount, duration, or scale marker.
    if original_tokens and not original_tokens.issubset(rewrite_tokens):
        return False
    return len(_clean(rewrite)) >= max(int(len(_clean(original)) * 0.65), 30)


_BULLET_MATCH_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "by", "at", "from", "as", "that", "this", "it", "its", "be", "is", "are",
    "was", "were", "will", "would", "should", "could", "can", "may", "might",
    "has", "have", "had", "do", "does", "did", "but", "if", "so",
}


def _bullet_match_tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w\s]", " ", _clean(text).lower())
    return {t for t in cleaned.split() if len(t) > 2 and t not in _BULLET_MATCH_STOPWORDS}


def _bullet_similarity(bullet: str, original: str) -> float:
    """Max-containment similarity. Returns the higher of:
    - fraction of original's tokens in bullet (handles LLM-elaborated original)
    - fraction of bullet's tokens in original (handles LLM-truncated original)
    Resume parsers often split bullets on line wraps, so LLM originals may be
    longer OR shorter than the parsed bullet."""
    orig_tokens = _bullet_match_tokens(original)
    bullet_tokens = _bullet_match_tokens(bullet)
    if not orig_tokens or not bullet_tokens:
        return 0.0
    intersection = len(orig_tokens & bullet_tokens)
    return max(intersection / len(orig_tokens), intersection / len(bullet_tokens))


def _apply_bullet_rewrites(original_bullets: list[str], rewrites: list[dict[str, Any]]) -> list[str]:
    candidates: list[dict[str, Any]] = [
        r for r in rewrites
        if _clean(r.get("original")) and _clean(r.get("rewritten"))
    ]
    used_indices: set[int] = set()
    result: list[str] = []
    for bullet in original_bullets:
        cleaned_bullet = _clean(bullet)
        best_idx = -1
        best_score = 0.0
        for idx, rewrite in enumerate(candidates):
            if idx in used_indices:
                continue
            original = _clean(rewrite.get("original"))
            if cleaned_bullet.lower() == original.lower():
                best_idx = idx
                best_score = 1.0
                break
            score = _bullet_similarity(cleaned_bullet, original)
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx >= 0 and best_score >= 0.6:
            rewrite = candidates[best_idx]
            rewritten = _normalize_bullet_text(_clean(rewrite.get("rewritten")))
            rewritten = _BULLET_MARKER_RE.sub("", rewritten).strip()
            change_type = (rewrite.get("change_type") or "reframe").lower()
            if rewritten and _should_use_rewrite(cleaned_bullet, rewritten, change_type=change_type):
                used_indices.add(best_idx)
                result.append(rewritten)
                continue
        result.append(cleaned_bullet)
    return [bullet for bullet in result if bullet]


def _filter_rewrites_by_decisions(
    rewrites: list[dict[str, Any]] | None,
    decisions: dict[str, str] | None,
    *,
    auto_accept_inferred: bool = False,
) -> list[dict[str, Any]]:
    """Apply accept/reject/pending decisions to a rewrite list.

    Rules:
    - keyword/reframe: included unless explicitly rejected.
    - inferred_claim: included only if explicitly accepted, OR auto_accept flag on.
    """
    decisions = decisions or {}
    allowed: list[dict[str, Any]] = []
    for rewrite in rewrites or []:
        rewrite_id = rewrite.get("id")
        decision = (decisions.get(rewrite_id) or "").lower() if rewrite_id else ""
        change_type = (rewrite.get("change_type") or "reframe").lower()
        if decision == "rejected":
            continue
        if change_type == "inferred_claim":
            if decision == "accepted" or auto_accept_inferred:
                allowed.append(rewrite)
            continue
        allowed.append(rewrite)
    return allowed


def _index_rewrites(
    rewrites: list[dict[str, Any]] | None,
    *,
    section_name: str,
    index_field: str,
) -> dict[int, list[dict[str, Any]]]:
    indexed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for rewrite in rewrites or []:
        section = _clean(rewrite.get("section")) or "experience"
        idx = rewrite.get(index_field)
        if section == section_name and isinstance(idx, int):
            indexed[idx].append(rewrite)
        elif (
            section_name == "experience"
            and not _clean(rewrite.get("section"))
            and index_field == "experience_index"
            and isinstance(idx, int)
        ):
            indexed[idx].append(rewrite)
    return indexed


def _rewrite_is_rendered_in_current_artifact(
    rewrite: dict[str, Any],
    decision: str,
    *,
    auto_accept_inferred: bool,
) -> bool:
    if decision == "rejected":
        return False
    change_type = (rewrite.get("change_type") or "reframe").lower()
    if change_type == "inferred_claim":
        return decision == "accepted" or auto_accept_inferred
    return True
