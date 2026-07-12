"""Redline diff PDF generation for resume artifacts."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any


from app.services.resume_artifact.latex import _PDF_RENDER_SEMAPHORE, _latex_escape_preserving_spacing, render_resume_artifact_pdf
from app.services.resume_artifact.rewrites import _rewrite_is_rendered_in_current_artifact
from app.services.resume_artifact.textnorm import _clean, _latex_plain_text, _quantifiable_measure_spans
from app.config import settings
from app.utils.sandboxed_process import run_in_sandbox_async

logger = logging.getLogger(__name__)


_REDLINE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "by", "at", "from", "as", "that", "this", "it", "its", "be", "is", "are",
    "was", "were", "will", "would", "should", "could", "can", "may", "might",
    "has", "have", "had", "do", "does", "did", "but", "if", "so", "using",
    "used", "while", "through",
}


def _redline_normalize_token(token: str) -> str:
    return re.sub(r"[^a-z0-9+#.%]", "", token.lower()).strip(".,;:")


def _redline_tokenize(text: str) -> list[str]:
    return re.findall(r"\S+\s*", text or "")


def _redline_diff_segments(original: str, rewritten: str) -> list[tuple[str, str]]:
    """Return ordered word-level segments for rendered PDF redlines."""
    original_tokens = _redline_tokenize(original)
    rewritten_tokens = _redline_tokenize(rewritten)
    original_keys = [_redline_normalize_token(token) for token in original_tokens]
    rewritten_keys = [_redline_normalize_token(token) for token in rewritten_tokens]
    dp = [
        [0 for _ in range(len(rewritten_tokens) + 1)]
        for _ in range(len(original_tokens) + 1)
    ]

    for i in range(len(original_tokens) - 1, -1, -1):
        for j in range(len(rewritten_tokens) - 1, -1, -1):
            if original_keys[i] and original_keys[i] == rewritten_keys[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])

    segments: list[tuple[str, str]] = []

    def append(kind: str, text: str) -> None:
        if not text:
            return
        if segments and segments[-1][0] == kind:
            segments[-1] = (kind, segments[-1][1] + text)
        else:
            segments.append((kind, text))

    i = 0
    j = 0
    while i < len(original_tokens) or j < len(rewritten_tokens):
        if (
            i < len(original_tokens)
            and j < len(rewritten_tokens)
            and original_keys[i]
            and original_keys[i] == rewritten_keys[j]
        ):
            append("same", rewritten_tokens[j])
            i += 1
            j += 1
        elif j < len(rewritten_tokens) and (
            i >= len(original_tokens) or dp[i][j + 1] >= dp[i + 1][j]
        ):
            append("added", rewritten_tokens[j])
            j += 1
        elif i < len(original_tokens):
            append("removed", original_tokens[i])
            i += 1

    return segments


def _redline_compare_text(text: str) -> str:
    text = _latex_plain_text(text).lower()
    text = re.sub(r"[^a-z0-9+#.%]+", " ", text)
    return _clean(text)


def _redline_significant_tokens(text: str) -> set[str]:
    return {
        token
        for token in _redline_compare_text(text).split()
        if len(token) > 2 and token not in _REDLINE_STOPWORDS
    }


def _find_redline_target_line(
    lines: list[str],
    target_text: str,
    used_indices: set[int],
) -> int | None:
    target_tokens = _redline_significant_tokens(target_text)
    target_compare = _redline_compare_text(target_text)
    if not target_compare:
        return None
    best_index: int | None = None
    best_score = 0.0

    for idx, line in enumerate(lines):
        if idx in used_indices or not line.lstrip().startswith(r"\item"):
            continue
        line_compare = _redline_compare_text(line)
        if not line_compare:
            continue
        line_tokens = _redline_significant_tokens(line)
        if len(line_tokens) < 3 and target_compare not in line_compare:
            continue
        overlap = (
            len(target_tokens & line_tokens) / len(target_tokens)
            if target_tokens
            else 0.0
        )
        containment = (
            1.0
            if target_compare in line_compare
            or (len(target_compare) > 40 and target_compare[:40] in line_compare)
            else 0.0
        )
        score = max(overlap, containment)
        if score > best_score:
            best_score = score
            best_index = idx

    threshold = 0.55 if len(target_tokens) >= 3 else 1.0
    return best_index if best_index is not None and best_score >= threshold else None


def _latex_redline_text(original: str, rewritten: str) -> str:
    pieces: list[str] = []
    for kind, text in _redline_diff_segments(original, rewritten):
        escaped = (
            _latex_escape_preserving_spacing(text)
            if kind == "removed"
            else _latex_metrics_preserving_spacing(text)
        )
        if not escaped:
            continue
        if kind == "added":
            pieces.append(r"{\sethlcolor{green!25}\hl{" + escaped + "}}")
        elif kind == "removed":
            pieces.append(r"{\color{red!70!black}\sout{" + escaped + "}}")
        else:
            pieces.append(escaped)
    return "".join(pieces).strip()




def _latex_metrics_preserving_spacing(value: str | None) -> str:
    text = value or ""
    spans = _quantifiable_measure_spans(text)
    if not spans:
        return _latex_escape_preserving_spacing(text)

    rendered: list[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        rendered.append(_latex_escape_preserving_spacing(text[cursor:start]))
        rendered.append(
            rf"\textbf{{{_latex_escape_preserving_spacing(text[start:end])}}}"
        )
        cursor = end
    rendered.append(_latex_escape_preserving_spacing(text[cursor:]))
    return "".join(rendered)


def _has_latex_package(content: str, package_name: str) -> bool:
    pattern = rf"\\usepackage(?:\[[^\]]+\])?\{{{re.escape(package_name)}\}}"
    return re.search(pattern, content) is not None


def _inject_redline_latex_packages(content: str) -> str:
    additions: list[str] = []
    if not _has_latex_package(content, "ulem"):
        additions.append(r"\usepackage[normalem]{ulem}")
    if not _has_latex_package(content, "xcolor"):
        additions.append(r"\usepackage{xcolor}")
    if not _has_latex_package(content, "soul"):
        additions.append(r"\usepackage{soul}")
    if r"\sethlcolor" not in content:
        additions.append(r"\sethlcolor{green!25}")
    if r"\soulregister\textbf" not in content:
        additions.append(r"\soulregister\textbf7")

    if not additions:
        return content
    marker = r"\begin{document}"
    if marker not in content:
        return "\n".join(additions) + "\n" + content
    return content.replace(marker, "\n".join(additions) + "\n" + marker, 1)


def _build_redline_resume_artifact_content(
    content: str,
    rewrites: list[dict[str, Any]] | None,
    decisions: dict[str, str] | None = None,
    *,
    auto_accept_inferred: bool = False,
) -> str:
    """Overlay rewrite redlines directly onto generated resume LaTeX content.

    This is a review artifact only: it renders the same resume page with
    additions highlighted and removed wording struck through so users can see
    edits in the visual PDF layout before using the final clean PDF.
    """
    if not content or not rewrites:
        return _inject_redline_latex_packages(content)

    decisions = decisions or {}
    lines = content.splitlines()
    used_indices: set[int] = set()

    for rewrite in rewrites:
        rewrite_id = str(rewrite.get("id") or "")
        decision = str(
            decisions.get(rewrite_id)
            or rewrite.get("decision")
            or "pending"
        ).lower()
        if decision == "rejected":
            continue
        original = _clean(rewrite.get("original"))
        rewritten = _clean(rewrite.get("rewritten"))
        if not original or not rewritten:
            continue

        rendered = _rewrite_is_rendered_in_current_artifact(
            rewrite,
            decision,
            auto_accept_inferred=auto_accept_inferred,
        )
        search_text = rewritten if rendered else original
        line_index = _find_redline_target_line(lines, search_text, used_indices)
        if line_index is None and rendered:
            line_index = _find_redline_target_line(lines, original, used_indices)
        if line_index is None:
            continue

        prefix_match = re.match(r"^(\s*\\item\s+)", lines[line_index])
        prefix = prefix_match.group(1) if prefix_match else r"\item "
        lines[line_index] = prefix + _latex_redline_text(original, rewritten)
        used_indices.add(line_index)

    return _inject_redline_latex_packages("\n".join(lines) + "\n")


def render_resume_artifact_redline_pdf(
    content: str,
    rewrites: list[dict[str, Any]] | None,
    decisions: dict[str, str] | None = None,
    *,
    auto_accept_inferred: bool = False,
) -> bytes:
    """Render a review-only PDF with visible redline marks on the resume page."""
    redline_content = _build_redline_resume_artifact_content(
        content,
        rewrites,
        decisions,
        auto_accept_inferred=auto_accept_inferred,
    )
    return render_resume_artifact_pdf(redline_content)


async def render_resume_artifact_redline_pdf_async(
    content: str,
    rewrites: list[dict[str, Any]] | None,
    decisions: dict[str, str] | None = None,
    *,
    auto_accept_inferred: bool = False,
) -> bytes:
    """Async wrapper around ``render_resume_artifact_redline_pdf`` (audit H1)."""
    async with _PDF_RENDER_SEMAPHORE:
        if settings.render_remote_enabled:
            from app.tasks.render import render_redline_pdf

            task = render_redline_pdf.apply_async(
                args=[content, rewrites, decisions, auto_accept_inferred],
                queue="render",
            )
            try:
                result = await asyncio.to_thread(
                    task.get,
                    timeout=settings.render_task_timeout_seconds,
                    propagate=True,
                )
            except Exception as exc:
                task.revoke(terminate=True)
                raise ValueError("Remote redline rendering failed safely.") from exc
            if not isinstance(result, bytes) or not result.startswith(b"%PDF"):
                raise ValueError("Remote renderer returned an invalid PDF.")
            if len(result) > settings.parser_sandbox_output_bytes:
                raise ValueError("Remote renderer returned an oversized PDF.")
            return result
        return await run_in_sandbox_async(
            "app.services.resume_artifact.redline",
            "render_resume_artifact_redline_pdf",
            content,
            rewrites,
            decisions,
            timeout_seconds=settings.latex_render_timeout_seconds + 3,
            memory_bytes=settings.parser_sandbox_memory_bytes,
            cpu_seconds=settings.parser_sandbox_cpu_seconds,
            output_bytes=settings.parser_sandbox_output_bytes,
            auto_accept_inferred=auto_accept_inferred,
        )
