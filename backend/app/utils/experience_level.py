"""Infer experience level from job metadata.

The classifier intentionally separates seniority evidence from broad words
like "manager" and "graduate" because both are common false positives on job
boards. Callers that only have a title can still use ``classify_experience_level``;
ingestion should prefer ``classify_experience_level_metadata``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class JobLevelResult:
    level: str
    confidence: float
    source: str
    reasons: list[str]


_DIRECT_INTERN_RE = re.compile(r"\b(intern|internship|co[- ]?op)\b", re.IGNORECASE)
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

_STRONG_NEW_GRAD_RE = re.compile(
    r"\b("
    r"new\s*(?:college\s*)?grad(?:uate)?"
    r"|entry[\s-]?level"
    r"|junior|jr\.?"
    r"|early[\s-]?career"
    r"|recent\s*grad(?:uate)?"
    r"|university\s+grad(?:uate)?"
    r"|college\s+grad(?:uate)?"
    r"|graduate\s+(program|scheme|role)"
    r"|0\s*[\-–]\s*2\s*(?:years?|yrs?)"
    r")\b",
    re.IGNORECASE,
)
_BROAD_GRADUATE_RE = re.compile(r"\bgraduate\b", re.IGNORECASE)
_SOURCE_NEW_GRAD_RE = re.compile(
    r"\b(student\s+program|new\s*grad|entry(?:[\s-]?level)?|graduate|associate|junior"
    r"|recent\s*grad|summer\s+analyst)\b",
    re.IGNORECASE,
)
_SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|architect|distinguished|fellow)\b",
    re.IGNORECASE,
)
_LEADERSHIP_RE = re.compile(
    r"\b(lead|director|vp|vice president|head\s+of|chief|engineering\s+manager"
    r"|manager,\s*(software|engineering|data|machine learning|infrastructure)"
    r"|software\s+engineering\s+manager|data\s+engineering\s+manager)\b",
    re.IGNORECASE,
)
_IC_MANAGER_RE = re.compile(
    r"\b(product|program|project|account|customer success|community|content|campaign"
    r"|partnership|relationship|marketing|sales|operations|success)\s+manager\b",
    re.IGNORECASE,
)
_YEARS_REQUIRED_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s*(?:of\s+)?"
    r"(?:relevant\s+)?(?:experience|exp)?",
    re.IGNORECASE,
)
_RANGE_YEARS_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*[\-–]\s*(\d+(?:\.\d+)?)\s*"
    r"(?:years?|yrs?)",
    re.IGNORECASE,
)
_ROMAN_LEVEL_RE = re.compile(
    r"\b(?:engineer|developer|scientist|analyst|designer|specialist|associate|consultant|manager)"
    r"\s+(I{1,3}|IV|V|VI)\b",
    re.IGNORECASE,
)


def _result(level: str, confidence: float, source: str, *reasons: str) -> JobLevelResult:
    return JobLevelResult(
        level=level,
        confidence=round(confidence, 2),
        source=source,
        reasons=[reason for reason in reasons if reason],
    )


def _normalize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(str(item) for item in value if item)
    return re.sub(r"\s+", " ", str(value).strip())


def _is_intern_level(text: str) -> bool:
    if _DIRECT_INTERN_RE.search(text):
        return True
    if _STUDENT_ROLE_EXCLUSION_RE.search(text):
        return False
    return bool(_STUDENT_ROLE_RE.search(text))


def _min_years_from_value(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("minExperience", "min_experience", "minimum", "min", "years"):
            parsed = _min_years_from_value(value.get(key))
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, list):
        values = [parsed for item in value if (parsed := _min_years_from_value(item)) is not None]
        return min(values) if values else None

    text = _normalize(value)
    range_match = _RANGE_YEARS_RE.search(text)
    if range_match:
        return float(range_match.group(1))
    match = _YEARS_REQUIRED_RE.search(text)
    if match:
        return float(match.group(1))
    return None


def _min_years_from_description(description: str) -> float | None:
    range_match = _RANGE_YEARS_RE.search(description)
    if range_match:
        return float(range_match.group(1))
    matches = [float(match) for match in _YEARS_REQUIRED_RE.findall(description)]
    return min(matches) if matches else None


def _level_from_years(years: float) -> str:
    if years <= 2:
        return "new_grad"
    if years >= 6:
        return "senior"
    return "mid"


def _level_from_roman(title: str) -> JobLevelResult | None:
    match = _ROMAN_LEVEL_RE.search(title)
    if not match:
        return None
    roman = match.group(1).upper()
    if roman == "I":
        return _result("new_grad", 0.7, "roman_numeral", "level_i")
    if roman in {"II", "III"}:
        return _result("mid", 0.75, "roman_numeral", f"level_{roman.lower()}")
    if roman in {"IV", "V", "VI"}:
        return _result("senior", 0.82, "roman_numeral", f"level_{roman.lower()}")
    return None


def _is_senior_title(title: str) -> bool:
    if _SENIOR_RE.search(title) or _LEADERSHIP_RE.search(title):
        return True
    if re.search(r"\bmanager\b", title, flags=re.IGNORECASE):
        return not _IC_MANAGER_RE.search(title)
    return False


def classify_experience_level_metadata(
    title: str,
    *,
    description: str | None = None,
    source: str | None = None,
    level_label: str | None = None,
    employment_type: object | None = None,
    min_experience: object | None = None,
) -> JobLevelResult:
    """Return a structured level classification for a job posting."""
    title_text = _normalize(title)
    label_text = _normalize(level_label)
    description_text = _normalize(description)
    employment_text = _normalize(employment_type)
    source_key = _normalize(source).lower()
    title_and_label = f"{title_text} {label_text}".strip()
    all_text = f"{title_and_label} {description_text}".strip()

    if "intern" in employment_text or _is_intern_level(title_and_label):
        return _result("intern", 0.95, "source_label_or_title", "internship_signal")

    if source_key == "newgrad_jobs" and _SOURCE_NEW_GRAD_RE.search(title_and_label):
        if _is_intern_level(title_and_label):
            return _result("intern", 0.95, "newgrad_jobs_level_label", "student_program")
        return _result("new_grad", 0.92, "newgrad_jobs_level_label", "newgrad_source_label")

    if _STRONG_NEW_GRAD_RE.search(title_and_label):
        return _result("new_grad", 0.9, "title_or_label", "explicit_new_grad_signal")

    senior_title = _is_senior_title(title_text)
    if senior_title:
        return _result("senior", 0.9, "title", "senior_title_signal")

    roman = _level_from_roman(title_text)
    if roman:
        return roman

    years = _min_years_from_value(min_experience)
    years_source = "source_min_experience"
    if years is None:
        years = _min_years_from_description(description_text)
        years_source = "description_years_required"
    if years is not None:
        return _result(_level_from_years(years), 0.78, years_source, f"{years:g}_years_required")

    if source_key == "newgrad_jobs" and _BROAD_GRADUATE_RE.search(all_text):
        return _result("new_grad", 0.72, "newgrad_jobs_text", "broad_graduate_signal")

    if _BROAD_GRADUATE_RE.search(title_and_label):
        return _result("new_grad", 0.62, "title_or_label", "broad_graduate_signal")

    return _result("mid", 0.45, "default", "no_strong_level_signal")


def classify_experience_level(title: str) -> str:
    """Return one of: intern, new_grad, mid, senior."""
    return classify_experience_level_metadata(title).level


def classify_experience_level_for_job(
    title: str,
    *,
    source: str | None = None,
    level_label: str | None = None,
) -> str:
    """Backwards-compatible source-aware level classifier."""
    return classify_experience_level_metadata(
        title,
        source=source,
        level_label=level_label,
    ).level
