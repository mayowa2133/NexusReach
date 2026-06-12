"""Affinity signals between the user and discovered candidates.

A shared school or past employer measurably raises reply rates and changes
who the *right* first contact is. Affinity is computed opportunistically from
whatever evidence exists - enriched candidate profiles (Proxycurl education /
experiences) or the search snippet - against the user's parsed resume. It is
an annotation plus a small, late ranking component: like warm paths, it only
reorders candidates that already passed every safety gate.
"""

from __future__ import annotations

import re
from typing import Any

_MIN_NAME_LEN = 5
_GENERIC_INSTITUTION_WORDS = {
    "university", "college", "institute", "school", "state", "technology",
    "company", "inc", "llc", "ltd", "corp", "group", "the", "of", "and",
}


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _distinctive(name: str) -> bool:
    """A name is matchable when it has a distinctive token, not just generics."""
    if len(name) < _MIN_NAME_LEN:
        return False
    tokens = [t for t in re.split(r"[^a-z0-9]+", name) if t]
    return any(t not in _GENERIC_INSTITUTION_WORDS and len(t) > 2 for t in tokens)


def _user_anchors(resume_parsed: dict | None) -> tuple[list[str], list[str]]:
    """Extract the user's schools and past companies from the parsed resume."""
    schools: list[str] = []
    companies: list[str] = []
    parsed = resume_parsed or {}
    for edu in parsed.get("education") or []:
        school = _normalize((edu or {}).get("school"))
        if school and _distinctive(school):
            schools.append(school)
    for exp in parsed.get("experience") or []:
        company = _normalize((exp or {}).get("company"))
        if company and _distinctive(company):
            companies.append(company)
    return schools, companies


def _candidate_texts(candidate: dict) -> tuple[list[str], list[str], str]:
    """Candidate-side schools, companies, and free-text fallback."""
    profile_data = candidate.get("profile_data") if isinstance(candidate.get("profile_data"), dict) else {}
    schools = [
        _normalize((edu or {}).get("school"))
        for edu in (profile_data.get("education") or [])
    ]
    companies = [
        _normalize((exp or {}).get("company"))
        for exp in (profile_data.get("experiences") or [])
    ]
    snippet = _normalize(
        " ".join(
            str(part)
            for part in (
                candidate.get("snippet"),
                profile_data.get("public_snippet"),
                profile_data.get("linkedin_result_title"),
            )
            if part
        )
    )
    return [s for s in schools if s], [c for c in companies if c], snippet


def compute_affinity(resume_parsed: dict | None, candidate: dict, *, target_company: str | None = None) -> dict | None:
    """Return {"type": "school"|"past_company", "name": <display>} or None.

    The target company itself never counts as a shared past employer - the
    candidate working there is the whole point of the search.
    """
    schools, companies = _user_anchors(resume_parsed)
    if not schools and not companies:
        return None
    target = _normalize(target_company)
    cand_schools, cand_companies, snippet = _candidate_texts(candidate)

    for school in schools:
        if any(school == s or school in s or s in school for s in cand_schools if s):
            return {"type": "school", "name": school.title()}
        if school in snippet:
            return {"type": "school", "name": school.title()}

    for company in companies:
        if target and (company == target or company in target or target in company):
            continue
        if any(company == c or company in c or c in company for c in cand_companies if c):
            return {"type": "past_company", "name": company.title()}
    return None


def annotate_affinity(
    candidates: list[dict],
    resume_parsed: dict | None,
    *,
    target_company: str | None = None,
) -> int:
    """Stamp affinity on matching candidates in place; returns match count."""
    if not resume_parsed:
        return 0
    matched = 0
    for candidate in candidates:
        affinity = compute_affinity(resume_parsed, candidate, target_company=target_company)
        if affinity is None:
            continue
        candidate["_affinity"] = affinity
        candidate["profile_data"] = {
            **(candidate.get("profile_data") or {}),
            "affinity": affinity,
        }
        matched += 1
    return matched


def affinity_rank(data: dict[str, Any]) -> int:
    """Late sort component: shared background wins ties, never safety."""
    return 0 if data.get("_affinity") else 1
