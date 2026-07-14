"""Merge a self-captured LinkedIn profile into the user's profile (Workstream F).

Non-destructive: fills blank profile fields, unions skills, and appends
positions/education into ``resume_parsed`` under the same keys the affinity
scorer reads (``experience[].company`` / ``education[].school``) so shared-
school / past-employer warm-path signals light up without a resume. A parsed
resume stays authoritative — nothing it already provided is overwritten.
"""

from datetime import datetime, timezone
from typing import Any

from app.models.profile import Profile
from app.utils.linkedin import normalize_linkedin_url


def _clean(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _merge_skills(existing: list[Any] | None, incoming: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for skill in [*(existing or []), *(incoming or [])]:
        cleaned = _clean(skill)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _append_distinct(
    existing: list[Any] | None,
    incoming: list[dict[str, Any]] | None,
    key_field: str,
) -> list[dict[str, Any]]:
    """Append incoming rows whose key_field isn't already present (case-insensitive)."""
    result = [row for row in (existing or []) if isinstance(row, dict)]
    seen = {
        _clean(row.get(key_field)).lower()
        for row in result
        if _clean(row.get(key_field))
    }
    for row in incoming or []:
        if not isinstance(row, dict):
            continue
        key = _clean(row.get(key_field))
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        result.append({k: v for k, v in row.items() if v is not None})
    return result


def merge_linkedin_profile(profile: Profile, payload: dict[str, Any]) -> dict[str, Any]:
    """Mutate ``profile`` in place from a self-captured LinkedIn payload.

    Returns a summary of what changed for the UI. Does not commit.
    """
    changed: dict[str, Any] = {
        "filled_name": False,
        "filled_bio": False,
        "filled_linkedin_url": False,
        "skills_added": 0,
        "positions_added": 0,
        "education_added": 0,
    }

    full_name = _clean(payload.get("full_name"))
    if full_name and not _clean(profile.full_name):
        profile.full_name = full_name
        changed["filled_name"] = True

    headline = _clean(payload.get("headline"))
    if headline and not _clean(profile.bio):
        profile.bio = headline
        changed["filled_bio"] = True

    normalized_url = normalize_linkedin_url(payload.get("linkedin_url"))
    if normalized_url and not _clean(profile.linkedin_url):
        profile.linkedin_url = normalized_url
        changed["filled_linkedin_url"] = True

    parsed = dict(profile.resume_parsed) if isinstance(profile.resume_parsed, dict) else {}

    incoming_skills = payload.get("skills") or []
    if incoming_skills:
        before = len(parsed.get("skills") or [])
        parsed["skills"] = _merge_skills(parsed.get("skills"), incoming_skills)
        changed["skills_added"] = max(0, len(parsed["skills"]) - before)

    incoming_positions = [
        {"title": _clean(p.get("title")), "company": _clean(p.get("company"))}
        for p in (payload.get("positions") or [])
        if isinstance(p, dict) and (_clean(p.get("title")) or _clean(p.get("company")))
    ]
    if incoming_positions:
        before = len(parsed.get("experience") or [])
        parsed["experience"] = _append_distinct(parsed.get("experience"), incoming_positions, "company")
        changed["positions_added"] = max(0, len(parsed["experience"]) - before)

    incoming_education = [
        {"school": _clean(e.get("school")), "degree": _clean(e.get("degree"))}
        for e in (payload.get("education") or [])
        if isinstance(e, dict) and _clean(e.get("school"))
    ]
    if incoming_education:
        before = len(parsed.get("education") or [])
        parsed["education"] = _append_distinct(parsed.get("education"), incoming_education, "school")
        changed["education_added"] = max(0, len(parsed["education"]) - before)

    parsed["linkedin_import"] = {
        "source": "companion",
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    profile.resume_parsed = parsed

    return changed
