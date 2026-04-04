"""Infer experience level from a job title string."""

import re

# Patterns checked in order — first match wins.
_INTERN_RE = re.compile(
    r"\b(intern|internship|co-?op)\b", re.IGNORECASE
)
_NEW_GRAD_RE = re.compile(
    r"\b(new\s*grad|entry[\s-]?level|junior|jr\.?|associate"
    r"|early[\s-]?career|graduate|recent\s*grad|0[\s-]?[–-][\s-]?2\s*y)"
    r"\b",
    re.IGNORECASE,
)
_SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|director|vp|architect"
    r"|distinguished|fellow|head\s+of|manager)\b",
    re.IGNORECASE,
)
_NEWGRAD_SOURCE_RE = re.compile(
    r"\b(new\s*grad|entry(?:[\s-]?level)?|graduate|associate|junior"
    r"|recent\s*grad|summer\s+analyst)\b",
    re.IGNORECASE,
)


def classify_experience_level(title: str) -> str:
    """Return one of: intern, new_grad, mid, senior."""
    if _INTERN_RE.search(title):
        return "intern"
    if _NEW_GRAD_RE.search(title):
        return "new_grad"
    if _SENIOR_RE.search(title):
        return "senior"
    return "mid"


def classify_experience_level_for_job(
    title: str,
    *,
    source: str | None = None,
    level_label: str | None = None,
) -> str:
    """Infer level with source-aware handling for newgrad-jobs rows."""
    if source != "newgrad_jobs":
        return classify_experience_level(title)

    combined = f"{title} {level_label or ''}"
    if _INTERN_RE.search(combined):
        return "intern"
    if _SENIOR_RE.search(combined) and not _NEWGRAD_SOURCE_RE.search(combined):
        return "senior"
    if _NEWGRAD_SOURCE_RE.search(combined):
        return "new_grad"
    if _SENIOR_RE.search(combined):
        return "senior"
    return classify_experience_level(title)
