"""Parsed-resume repair, normalization, and merging."""

from __future__ import annotations

import logging
import re
from typing import Any


from app.models.profile import Profile
from app.services.resume_parser import parse_resume_text, scrub_skill_list
from app.services.resume_artifact.textnorm import _BULLET_MARKER_RE, _clean, _merge_unique, _normalize_bullet_text, _split_description_bullets, _split_project_bullets

logger = logging.getLogger(__name__)


_FRAGMENT_LEADING_WORDS = {
    "and", "or", "but", "so", "then", "with", "using", "via", "for", "to",
    "from", "of", "in", "on", "at", "by", "as", "the", "a", "an",
}


def _is_valid_project_name(name: str | None) -> bool:
    """Reject project names that look like prose fragments.

    Real project names: short noun phrases, title-cased, no terminal period.
    Bogus: lowercase start, conjunction start, ends in period without title-case.
    """
    cleaned = _clean(name)
    if not cleaned:
        return False
    if len(cleaned) > 80:
        return False
    words = cleaned.split()
    if not words:
        return False
    first = words[0]
    if first.lower() in _FRAGMENT_LEADING_WORDS:
        return False
    if first[:1].islower():
        return False
    # Reject prose-like endings (trailing period without a strong title signal).
    has_title_signal = bool(re.search(r"\bGitHub\b|\bhttps?://", cleaned)) or any(
        w[:1].isupper() and w.lower() not in _FRAGMENT_LEADING_WORDS for w in words[1:]
    )
    if cleaned.rstrip().endswith((".", "!", "?")) and not has_title_signal:
        return False
    # Too many words -> likely a sentence.
    if len(words) > 10:
        return False
    return True


_PROJECT_HEADER_INLINE_RE = re.compile(
    r"(?m)^([A-Z][\w .+\-/]{1,60}(?:\s*\([^)]*GitHub[^)]*\))?)\s*$"
)


def _extract_embedded_project(description: str) -> tuple[str, str] | None:
    """Detect a project header buried inside a description blob.

    Returns (header_name, remaining_description) if a line that looks like
    a project header (e.g. ``ClipForge (GitHub: ClipForge)``) appears in
    ``description``; the remainder is everything after that header.
    """
    if not description:
        return None
    lines = description.split("\n")
    for idx, line in enumerate(lines):
        candidate = line.strip()
        if not candidate or _BULLET_MARKER_RE.match(candidate):
            continue
        if _is_valid_project_name(candidate) and "GitHub" in candidate:
            header = candidate
            remainder = "\n".join(lines[idx + 1:]).strip()
            return header, remainder
    return None


def _repair_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coalesce parser-fragmented project entries.

    PDF wrap-induced fragments produce pseudo-projects whose ``name`` is a
    sentence fragment and whose ``description`` is actually the next bullet
    of the prior real project. Roll those fragments back into the previous
    valid project, and split out embedded project headers found inside
    descriptions.
    """
    if not projects:
        return []
    repaired: list[dict[str, Any]] = []

    def _ensure_bullets(entry: dict[str, Any]) -> list[str]:
        bullets = entry.get("bullets")
        if not bullets:
            bullets = _split_description_bullets(entry.get("description"))
            entry["bullets"] = bullets
        return entry["bullets"]

    def _norm_list(items: list[str]) -> list[str]:
        out = []
        for b in items:
            n = _normalize_bullet_text(b)
            if n:
                out.append(n)
        return out

    for project in projects:
        name = _clean(project.get("name"))
        desc = project.get("description") or ""
        bullets = _norm_list(list(project.get("bullets") or []))

        if _is_valid_project_name(name):
            entry = {**project, "name": name, "bullets": bullets or _split_description_bullets(desc)}
            repaired.append(entry)
            embedded = _extract_embedded_project(desc)
            if embedded:
                header, remainder = embedded
                # Trim the embedded header out of the parent description/bullets.
                entry["bullets"] = [b for b in entry["bullets"] if header not in b]
                repaired.append({
                    "name": header,
                    "url": None,
                    "link_label": None,
                    "technologies": [],
                    "bullets": _split_description_bullets(remainder),
                    "description": remainder,
                })
            continue

        # Fragment row: check if its description embeds a new project header
        # (e.g. ClipForge buried inside another fragment's description).
        embedded = _extract_embedded_project(desc)
        if embedded and repaired:
            header, remainder = embedded
            # Preceding text up to the header belongs to the prior project.
            head_idx = desc.find(header)
            preface = desc[:head_idx].strip() if head_idx > 0 else ""
            prev_bullets = _ensure_bullets(repaired[-1])
            name_tail = _normalize_bullet_text(name)
            if name_tail and prev_bullets:
                prev_bullets[-1] = _normalize_bullet_text(f"{prev_bullets[-1]} {name_tail}")
            elif name_tail:
                prev_bullets.append(name_tail)
            for frag in _split_description_bullets(preface):
                prev_bullets.append(frag)
            repaired.append({
                "name": header,
                "url": None,
                "link_label": None,
                "technologies": [],
                "bullets": _split_description_bullets(remainder),
                "description": remainder,
            })
            continue

        # Plain fragment: glue back into the most recent valid project.
        if not repaired:
            continue
        prev_bullets = _ensure_bullets(repaired[-1])
        name_tail = _normalize_bullet_text(name)
        if name_tail and prev_bullets:
            prev_bullets[-1] = _normalize_bullet_text(f"{prev_bullets[-1]} {name_tail}")
        elif name_tail:
            prev_bullets.append(name_tail)
        for frag in _split_description_bullets(desc):
            prev_bullets.append(frag)

    # De-dup empty entries.
    return [p for p in repaired if (p.get("bullets") or p.get("description"))]


def _normalize_experience_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Repair experience entries where parser swapped company/title.

    Some legacy parsed data has ``company`` populated with ``"Title <City, ST>"``
    and ``title`` populated with ``"<Company> <Dates>"`` because the parser
    mis-detected the date row. Detect this and swap+repair.
    """
    company = (item.get("company") or "").strip()
    title = (item.get("title") or "").strip()
    location = (item.get("location") or "").strip() if item.get("location") else ""
    start = (item.get("start_date") or "").strip() if item.get("start_date") else ""
    end = (item.get("end_date") or "").strip() if item.get("end_date") else ""

    # Lazy import to avoid circular: regex/helpers from parser.
    from app.services.resume_parser import (
        DATE_RANGE_RE,
        LOCATION_SUFFIX_RE,
        _parse_title_location,
    )

    raw_bullets = item.get("bullets") or []
    norm_bullets = [_normalize_bullet_text(b) for b in raw_bullets if _normalize_bullet_text(b)]
    if norm_bullets != raw_bullets:
        item = {**item, "bullets": norm_bullets}

    title_has_dates = bool(DATE_RANGE_RE.search(title))
    needs_full_repair = (
        not start
        and (not end or end.lower() in {"present", ""})
        and title_has_dates
    )
    if needs_full_repair:
        date_match = DATE_RANGE_RE.search(title)
        new_start = date_match.group("start").strip()
        new_end = date_match.group("end").strip()
        new_company = title[: date_match.start()].strip().rstrip("|-–—,").strip()
        new_title, new_location = _parse_title_location(company)
        return {
            **item,
            "company": new_company or company,
            "title": new_title or title,
            "location": new_location or location or "",
            "start_date": new_start,
            "end_date": None if new_end.lower() in {"present", "current"} else new_end,
        }

    # Lighter swap: dates are correct but company/title are swapped because
    # the parser bound the role line as company. Detect via location suffix
    # ("Title, City, ST") on the company field that the title lacks.
    company_has_loc = bool(LOCATION_SUFFIX_RE.match(company))
    title_has_loc = bool(LOCATION_SUFFIX_RE.match(title))
    if company_has_loc and not title_has_loc and not title_has_dates:
        new_title, new_location = _parse_title_location(company)
        return {
            **item,
            "company": title,
            "title": new_title or company,
            "location": new_location or location or "",
        }

    return item


def _normalize_education_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Repair education entries where institution/degree were swapped or
    glued to a location suffix.

    Legacy stored data often puts the degree line into ``institution`` and the
    university into ``degree``. Detect via "University"/"College"/"Institute"
    keyword presence, then split any location suffix off the degree line.
    """
    from app.services.resume_parser import LOCATION_SUFFIX_RE, _parse_title_location

    institution = (item.get("institution") or "").strip()
    degree = (item.get("degree") or "").strip()
    field = (item.get("field") or "").strip()
    location = (item.get("location") or "").strip()

    INSTITUTION_HINTS = ("University", "College", "Institute", "School", "Academy", "Polytechnic")
    inst_looks_like_degree = not any(h in institution for h in INSTITUTION_HINTS)
    degree_looks_like_institution = any(h in degree for h in INSTITUTION_HINTS)

    new_item = dict(item)
    if inst_looks_like_degree and degree_looks_like_institution:
        new_item["institution"] = degree
        new_item["degree"] = institution
        new_item["field"] = institution if not field or field == degree else field

    # Split trailing "City, ST" off the degree.
    degree_now = (new_item.get("degree") or "").strip()
    if LOCATION_SUFFIX_RE.search(degree_now):
        split_degree, split_loc = _parse_title_location(degree_now)
        if split_loc:
            new_item["degree"] = split_degree
            if not new_item.get("field") or new_item.get("field") == degree_now:
                new_item["field"] = split_degree
            if not location:
                new_item["location"] = split_loc
    return new_item


def _merge_project_records(existing: list[dict], reparsed: list[dict]) -> list[dict]:
    existing_by_name = {
        _clean(project.get("name")).lower(): project
        for project in existing
        if _clean(project.get("name"))
    }
    merged: list[dict] = []
    seen_names: set[str] = set()
    for project in reparsed:
        name_key = _clean(project.get("name")).lower()
        existing_project = existing_by_name.get(name_key, {})
        bullets = project.get("bullets") or _split_project_bullets(project.get("description"))
        merged.append({
            **existing_project,
            **project,
            "bullets": bullets or existing_project.get("bullets") or _split_project_bullets(existing_project.get("description")),
            "technologies": _merge_unique([
                *(project.get("technologies") or []),
                *(existing_project.get("technologies") or []),
            ]),
            "url": project.get("url") or existing_project.get("url"),
            "link_label": project.get("link_label") or existing_project.get("link_label"),
        })
        if name_key:
            seen_names.add(name_key)

    for project in existing:
        name_key = _clean(project.get("name")).lower()
        if name_key and name_key not in seen_names:
            merged.append(project)

    return merged


def _merge_contact(existing: dict[str, Any], reparsed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    merged.update({key: value for key, value in reparsed.items() if value})
    merged["urls"] = _merge_unique([
        *(reparsed.get("urls") or []),
        *(existing.get("urls") or []),
    ])
    return merged


def _merge_resume_parsed(existing: dict | None, reparsed: dict | None) -> dict[str, Any]:
    existing = existing or {}
    reparsed = reparsed or {}

    merged: dict[str, Any] = {**existing}
    merged["contact"] = _merge_contact(existing.get("contact") or {}, reparsed.get("contact") or {})
    merged["skills"] = scrub_skill_list(_merge_unique([
        *(reparsed.get("skills") or []),
        *(existing.get("skills") or []),
    ]))
    raw_categories = reparsed.get("skills_by_category") or existing.get("skills_by_category") or {}
    merged["skills_by_category"] = {
        label: scrub_skill_list(values) for label, values in raw_categories.items()
    }
    raw_experience = reparsed.get("experience") or existing.get("experience") or []
    merged["experience"] = [_normalize_experience_entry(entry) for entry in raw_experience]
    raw_education = reparsed.get("education") or existing.get("education") or []
    merged["education"] = [_normalize_education_entry(entry) for entry in raw_education]
    merged["projects"] = _repair_projects(
        _merge_project_records(existing.get("projects") or [], reparsed.get("projects") or [])
    )
    merged["certificates"] = reparsed.get("certificates") or existing.get("certificates") or []
    return merged


def _extract_resume_data(profile: Profile) -> dict[str, Any]:
    reparsed = parse_resume_text(profile.resume_raw) if profile.resume_raw else {}
    return _merge_resume_parsed(profile.resume_parsed, reparsed)


def _find_contact_url(profile: Profile, contact: dict[str, Any], domain: str) -> str | None:
    explicit = {
        "linkedin.com": profile.linkedin_url,
        "github.com": profile.github_url,
    }.get(domain)
    if explicit:
        return explicit
    for url in contact.get("urls") or []:
        if domain in url:
            return url
    return profile.portfolio_url if domain == "portfolio" else None


def _resolve_github_username(profile: Profile, contact: dict[str, Any] | None) -> str | None:
    candidates: list[str] = []
    if profile.github_url:
        candidates.append(_clean(profile.github_url))
    for url in (contact or {}).get("urls") or []:
        clean_url = _clean(url)
        if "github.com/" in clean_url.lower() and "/in/" not in clean_url.lower():
            candidates.append(clean_url)
    for candidate in candidates:
        if "github.com/" not in candidate.lower():
            continue
        username = candidate.rstrip("/").split("github.com/", 1)[1].split("/", 1)[0].strip("/")
        if username and username.lower() not in {"in", "company", "orgs"}:
            return username
    return None


def _derive_project_url(
    project: dict[str, Any],
    profile: Profile,
    contact: dict[str, Any] | None = None,
) -> str | None:
    explicit_url = _clean(project.get("url"))
    if explicit_url:
        return explicit_url

    username = _resolve_github_username(profile, contact)
    if not username:
        return None

    link_label = _clean(project.get("link_label"))
    repo_name = ""
    if ":" in link_label:
        repo_name = _clean(link_label.split(":", 1)[1])
    elif link_label:
        repo_name = link_label

    if not repo_name:
        return None
    repo_name = re.sub(r"\s+", "-", repo_name)
    repo_name = re.sub(r"[^A-Za-z0-9._-]", "", repo_name)
    if not repo_name:
        return None
    return f"https://github.com/{username}/{repo_name}"
