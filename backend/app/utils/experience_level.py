"""Infer experience level from a job title string."""

import re

# Patterns checked in order — first match wins.
_DIRECT_INTERN_RE = re.compile(
    r"\b(intern|internship|co-?op)\b", re.IGNORECASE
)
_STUDENT_ROLE_RE = re.compile(
    r"\b("
    r"student\s+(program|trainee|worker|researcher|engineer|developer|analyst|associate|fellow)"
    r"|"
    r"(summer|fall|winter|spring)\s+(analyst|associate|engineer|developer|researcher|program)"
    r"|"
    r"(software|data|product|business|finance|research|engineering|quant|security|design)"
    r"[\w\s,/-]{0,50}\b(summer|fall|winter|spring)\s+\d{4}"
    r"|"
    r"(software|data|product|business|finance|research|engineering)\s+student"
    r"|"
    r"industrial\s+placement|placement\s+student"
    r")\b",
    re.IGNORECASE,
)
_STUDENT_ROLE_EXCLUSION_RE = re.compile(
    r"\b("
    r"student\s+(success|services|affairs)"
    r"|university\s+recruiting|campus\s+recruiting"
    r"|program\s+manager|recruiter|coordinator"
    r"|\b(manager|director)\b"
    r")\b",
    re.IGNORECASE,
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


def _is_intern_level(title: str) -> bool:
    if _DIRECT_INTERN_RE.search(title):
        return True
    if _STUDENT_ROLE_EXCLUSION_RE.search(title):
        return False
    return bool(_STUDENT_ROLE_RE.search(title))


def classify_experience_level(title: str) -> str:
    """Return one of: intern, new_grad, mid, senior."""
    if _is_intern_level(title):
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
    if _is_intern_level(combined):
        return "intern"
    if _SENIOR_RE.search(combined) and not _NEWGRAD_SOURCE_RE.search(combined):
        return "senior"
    if _NEWGRAD_SOURCE_RE.search(combined):
        return "new_grad"
    if _SENIOR_RE.search(combined):
        return "senior"
    return classify_experience_level(title)
