"""Role-bucket classification (recruiter / hiring manager / peer) for people discovery."""

import logging


from app.utils.job_context import (
    JobContext,
)

from app.services.people.identity import _keyword_in_text
from app.services.people.titles import CONTROLLED_LEAD_KEYWORDS, DIRECTOR_PLUS_KEYWORDS, MANAGER_TITLE_KEYWORDS, _SENIOR_LEADERSHIP_PREFIXES, _is_adjacent_recruiter_like, _is_ic_manager_title, _is_recruiter_like
logger = logging.getLogger(__name__)


def _classify_org_level(title: str, source: str = "", snippet: str = "") -> str:
    haystack = " ".join(part for part in [title, snippet, source] if part).lower()
    if any(keyword in haystack for keyword in DIRECTOR_PLUS_KEYWORDS):
        return "director_plus"
    # IC manager titles (Product Manager, Program Manager, etc.) are ICs
    # unless they carry a senior leadership prefix.
    if _is_ic_manager_title(haystack):
        title_lower = (title or "").lower()
        if _SENIOR_LEADERSHIP_PREFIXES.search(title_lower):
            return "manager"
        return "ic"
    if any(keyword in haystack for keyword in MANAGER_TITLE_KEYWORDS):
        return "manager"
    if any(keyword in haystack for keyword in CONTROLLED_LEAD_KEYWORDS):
        return "manager"
    return "ic"


def _classify_person(title: str, source: str = "", snippet: str = "") -> str:
    """Classify a result into recruiter, hiring_manager, or peer."""
    haystack = " ".join(part for part in [title, snippet, source] if part).lower()
    if _is_recruiter_like(haystack):
        return "recruiter"
    # IC manager titles (Product Manager, Program Manager, etc.) are peers
    # UNLESS they carry a senior leadership prefix (Group PM, Director of
    # Product, VP Product, Head of Product).
    if _is_ic_manager_title(haystack):
        title_lower = (title or "").lower()
        if _SENIOR_LEADERSHIP_PREFIXES.search(title_lower):
            return "hiring_manager"
        return "peer"
    if any(keyword in haystack for keyword in MANAGER_TITLE_KEYWORDS):
        return "hiring_manager"
    if any(keyword in haystack for keyword in CONTROLLED_LEAD_KEYWORDS):
        return "hiring_manager"
    return "peer"


def _compute_match_metadata(
    data: dict,
    person_type: str,
    context: JobContext | None = None,
) -> tuple[str, str | None]:
    """Classify a result as direct or next-best and explain why."""
    title = (data.get("title") or "").lower()
    snippet = (data.get("snippet") or "").lower()
    department = (data.get("department") or "").lower()
    haystack = " ".join(part for part in [title, snippet, department] if part)

    if person_type == "peer" and data.get("_weak_title"):
        return "next_best", "Current employment is verified, but the title specificity is weak."
    if person_type == "hiring_manager" and data.get("_senior_ic_fallback"):
        return "next_best", "Senior IC fallback at the target company."

    if person_type == "recruiter":
        if _is_adjacent_recruiter_like(title) or _is_adjacent_recruiter_like(snippet):
            return "adjacent", "Talent-acquisition contact at the target company."
        if context and context.department in {"engineering", "data_science"}:
            return "direct", "Recruiting title aligned to technical hiring."
        return "direct", "Recruiting title at the target company."

    if context:
        for keyword in context.team_keywords + context.domain_keywords:
            if _keyword_in_text(keyword, haystack):
                return "direct", f"Matched {keyword.replace('_', ' ')} context."

        department_label = context.department.replace("_", " ")
        if department_label in haystack:
            return "direct", f"Matched {department_label} context."

        if person_type == "hiring_manager":
            return "adjacent", f"Adjacent {department_label} manager at the target company."
        return "adjacent", f"Adjacent {department_label} teammate at the target company."

    if person_type == "hiring_manager":
        return "direct", "Relevant manager title at the target company."
    if person_type == "peer":
        return "direct", "Relevant teammate title at the target company."
    return "direct", None
