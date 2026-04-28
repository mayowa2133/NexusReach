"""Generate and persist submission-ready LaTeX resume artifacts for a job."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume_artifact import ResumeArtifact
from app.models.tailored_resume import TailoredResume
from app.models.user import User
from app.clients.llm_client import generate_message
from app.services.match_scoring import score_job
from app.services.resume_parser import parse_resume_text, scrub_skill_list
from app.services.resume_tailor import _normalize_bullet_rewrites, tailor_resume
from app.utils.company_identity import slugify_company_name


logger = logging.getLogger(__name__)


def _clean(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _slugify_label(value: str | None, fallback: str) -> str:
    slug = slugify_company_name(value) or ""
    return slug or fallback


_BULLET_MARKER_RE = re.compile(r"^[\-•·▪►]\s*")


_PARTICLE_CONCAT_RE = re.compile(
    r"\b(and|or|with|using|from|on|in|by|for|to|via|plus|of)([A-Z][a-z])"
)

# Same, for particle + ALL-CAPS acronym (e.g. "andLLM" -> "and LLM").
_PARTICLE_ACRONYM_RE = re.compile(
    r"\b(and|or|with|using|from|on|in|by|for|to|via|plus|of)([A-Z]{2,}\b)"
)

# Particle + lowercase-word patterns that PDF extraction commonly glues together.
# Conservative: explicit suffixes only, to avoid splitting real words like
# "android", "another", "without", "online", "today", etc.
_LOWER_CONCAT_RE = re.compile(
    r"\b(and|or|with|from|via|plus)("
    r"design|ensemble|data|test|tested|tests|build|builds|"
    r"deploy|deploys|implement|implements|integrate|integrates|"
    r"deliver|delivers|sample|samples|series|set|sets|focus|focused|"
    r"context|user|users|manage|managed|monitor|monitors|"
    r"maintain|maintained|virtual|rolling|stream|streams|"
    r"queries|query|service|services|model|models|api|apis|"
    r"client|clients|server|servers|database|databases|dashboard|"
    r"feature|features|metric|metrics|pipeline|pipelines|"
    r"workflow|workflows|signal|signals|library|libraries|"
    r"export|exports|import|imports|endpoint|endpoints|"
    r"preview|previews|release|releases|component|components|"
    r"session|sessions|request|requests|response|responses|"
    r"token|tokens|thread|threads|queue|queues"
    r")\b"
)

# Article ("a"/"an") + common single-letter-prefixed nouns that get glued.
_ARTICLE_CONCAT_RE = re.compile(
    r"\b(a|an)("
    r"virtual|sample|series|set|service|model|user|client|server|"
    r"database|dashboard|feature|metric|pipeline|workflow|signal|"
    r"library|design|context|focus|build|deploy|test|monitor"
    r")\b"
)


def _normalize_bullet_text(text: str) -> str:
    """Clean PDF-extraction artifacts:
    - join hyphenated line wraps (e.g. "archi-\ntecture" -> "architecture")
    - collapse intra-bullet soft wraps (newline inside a bullet -> space)
    - fix stray space-before-punctuation (e.g. "Swift ,Xcode" -> "Swift, Xcode")
    - re-insert dropped spaces between particle + Capital (e.g. "andPydantic"
      -> "and Pydantic", "onVirtual" -> "on Virtual")
    - re-insert dropped spaces for known particle+lower concats
      (e.g. "anddesign", "fromrolling", "avirtual")
    - normalize whitespace
    """
    if not text:
        return ""
    # Join hyphenated line-wraps: "archi-\ntecture" -> "architecture"
    text = re.sub(r"([A-Za-z])-\s*\n\s*([A-Za-z])", r"\1\2", text)
    # Collapse remaining newlines inside the bullet to a single space.
    text = re.sub(r"\s*\n\s*", " ", text)
    # Fix "word ,word" / "word , word" -> "word, word". Applies to , ; :
    text = re.sub(r"\s+([,;:])", r"\1", text)
    # Ensure space after comma/semicolon if a word follows immediately.
    text = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", text)
    # Space before `+Capital` when it looks like an N+1 enumeration boundary
    # (e.g. "LangChain +OpenAI" -> "LangChain + OpenAI"). Skip all-caps runs
    # like "+EV" which are acronym markers, not list joins.
    text = re.sub(r"(\+)([A-Z][a-z])", r"\1 \2", text)
    # Re-insert dropped spaces: particle directly glued to a Capital-Lower word.
    text = _PARTICLE_CONCAT_RE.sub(r"\1 \2", text)
    # Same for ALL-CAPS acronyms glued to a particle ("andLLM" -> "and LLM").
    text = _PARTICLE_ACRONYM_RE.sub(r"\1 \2", text)
    # Fix "word -word" (stray space before hyphen) -> "word-word"
    # when the hyphen joins two word tokens (not an em-dash-like pause).
    text = re.sub(r"([A-Za-z])\s+-([A-Za-z])", r"\1-\2", text)
    # Particle + lowercase-word concats from PDF (curated suffix list).
    text = _LOWER_CONCAT_RE.sub(r"\1 \2", text)
    text = _ARTICLE_CONCAT_RE.sub(r"\1 \2", text)
    # Collapse double spaces.
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _split_description_bullets(description: str | None) -> list[str]:
    """Split a description blob into individual bullets.

    Prefer real bullet markers (•/-/·/▪) at line starts. Lines that do NOT
    start with a marker are treated as continuations of the previous bullet
    (handles resume PDFs that wrap long bullets across lines).
    """
    text = (description or "").strip()
    if not text:
        return []

    raw_lines = [ln.strip() for ln in re.split(r"\n+", text) if ln.strip()]
    has_markers = any(_BULLET_MARKER_RE.match(ln) for ln in raw_lines)

    bullets: list[str] = []
    if has_markers:
        for ln in raw_lines:
            if _BULLET_MARKER_RE.match(ln):
                bullets.append(_BULLET_MARKER_RE.sub("", ln).strip())
            else:
                if bullets:
                    # Re-join with newline so _normalize_bullet_text can repair wraps.
                    bullets[-1] = f"{bullets[-1]}\n{ln}"
                else:
                    bullets.append(ln)
    else:
        bullets = raw_lines

    cleaned: list[str] = []
    for b in bullets:
        normalized = _normalize_bullet_text(b)
        if len(normalized) >= 2:
            cleaned.append(normalized)
    return cleaned


def _split_project_bullets(description: str | None) -> list[str]:
    parts = _split_description_bullets(description)
    if parts:
        return parts[:3]
    text = (description or "").strip()
    if not text:
        return []
    sentences = [
        _normalize_bullet_text(part).strip().lstrip("-•·▪ ").strip()
        for part in re.split(r"(?<=[.!?])\s+", text)
    ]
    return [part for part in sentences if len(part) > 2][:3]


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


def _ordered_skills(
    parsed_skills: list[str],
    emphasized: list[str],
    additions: list[str],
    keywords: list[str],
    project_technologies: list[str],
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for skill in [*emphasized, *parsed_skills, *project_technologies, *additions, *keywords]:
        normalized = _clean(skill).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(_clean(skill))
    return ordered[:24]


LANGUAGE_SKILLS = {
    "c", "c++", "java", "python", "javascript", "typescript", "html", "css",
    "sql", "mysql", "swift", "go", "rust", "kotlin", "scala", "r", "nosql",
}

METHODOLOGY_SKILLS = {
    "agile", "scrum", "object-oriented programming", "oop", "machine learning",
    "nlp", "time series analysis", "data visualization", "testing", "debugging",
    "restful api", "serverless", "distributed systems", "vip", "prompt engineering",
}


def _latex_escape(value: str | None) -> str:
    text = _clean(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("—", "-").replace("–", "-").replace("•", "-")
    return text


def _latex_url(value: str | None) -> str:
    return _clean(value).replace("\\", "/")


def _categorize_skills(skills: list[str]) -> tuple[list[str], list[str], list[str]]:
    languages: list[str] = []
    technologies: list[str] = []
    methodologies: list[str] = []

    seen: set[str] = set()
    for skill in skills:
        clean_skill = _clean(skill)
        normalized = clean_skill.lower()
        if not clean_skill or normalized in seen:
            continue
        seen.add(normalized)
        if normalized in LANGUAGE_SKILLS:
            languages.append(clean_skill)
        elif normalized in METHODOLOGY_SKILLS:
            methodologies.append(clean_skill)
        else:
            technologies.append(clean_skill)

    return languages[:12], technologies[:16], methodologies[:12]


def _extract_phone(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    match = re.search(r"(\+?1?[\s\-.(]*\d{3}[\s\-.)]*\d{3}[\s\-]*\d{4})", raw_text)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def _merge_unique(values: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean_value = _clean(value)
        normalized = clean_value.lower()
        if not clean_value or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(clean_value)
    return merged


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


def _metric_tokens(text: str) -> set[str]:
    return set(re.findall(r"\b\d[\d,]*\+?%?\b|\b\d+\+\b", text))


_METRIC_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<value>\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:\s*/\s*\$?\d+(?:\.\d+)?)?(?:\+|%|[KkMmBb])?)"
    r"(?![A-Za-z0-9])"
)

_METRIC_UNIT_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of",
    "on", "or", "over", "per", "the", "through", "to", "using", "via", "while",
    "with", "within",
}


def _quantifiable_measure_spans(text: str) -> list[tuple[int, int]]:
    """Return spans for numeric impact phrases worth bolding in resume bullets."""
    spans: list[tuple[int, int]] = []
    for match in _METRIC_VALUE_RE.finditer(text):
        start, end = match.span("value")
        value = match.group("value")
        cursor = end
        unit_count = 0

        while unit_count < 3:
            unit_match = re.match(r"\s+([A-Za-z][A-Za-z0-9+/#.-]*)", text[cursor:])
            if unit_match is None:
                break
            raw_unit = unit_match.group(1)
            unit = raw_unit.strip(".,;:")
            if not unit or unit.lower() in _METRIC_UNIT_STOPWORDS:
                break
            cursor += unit_match.start(1) + len(unit)
            unit_count += 1
            if cursor < len(text) and text[cursor] in ",.;:":
                break

        digits_only = re.sub(r"\D", "", value)
        is_bare_year = (
            len(digits_only) == 4
            and 1900 <= int(digits_only) <= 2099
            and not re.search(r"[+%KkMmBb$/]", value)
        )
        if is_bare_year and unit_count == 0:
            continue

        spans.append((start, cursor))
    return spans


def _should_use_rewrite(original: str, rewrite: str, *, change_type: str = "reframe") -> bool:
    original_tokens = _metric_tokens(original)
    rewrite_tokens = _metric_tokens(rewrite)
    # Inferred claims intentionally add content; they may not preserve every
    # metric token. For keyword/reframe we still require metric preservation.
    if change_type != "inferred_claim" and original_tokens and not (original_tokens & rewrite_tokens):
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


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "using", "used",
    "build", "team", "experience", "software", "engineer", "role", "work", "across",
    "your", "our", "you", "will", "are", "but", "not", "job", "company", "fullstack",
}

DEFAULT_EMPHASIS_TERMS = [
    "React", "ReactJS", "JavaScript", "TypeScript", "HTML", "CSS", "responsive",
    "accessible", "accessibility", "WCAG", "RESTful API", "RESTful APIs", "REST API",
    "Node.js", "Playwright", "Cypress", "CI/CD", "telemetry", "experimentation",
    "personalization", "component-based", "components", "Git", "cross-functional",
    "frontend", "full-stack", "testing", "debugging", "performance", "API Gateway",
    "automation", "modular", "scalable", "web applications",
]

FULLSTACK_ROLE_TERMS = (
    "frontend", "front-end", "fullstack", "full-stack", "react", "javascript",
    "typescript", "html", "css", "web application", "web applications",
)

FULLSTACK_RELEVANT_SKILLS = [
    "React", "JavaScript", "TypeScript", "HTML", "CSS", "Next.js", "Node.js",
    "RESTful APIs", "Playwright", "Cypress", "responsive UI development",
    "component-based architecture", "testing", "debugging", "telemetry", "CI/CD",
    "Git", "cross-functional collaboration",
]

ARTIFACT_PLAN_SYSTEM_PROMPT = """\
You are designing a one-page ATS-friendly resume artifact for a specific job.
Your task is to decide which existing resume bullets deserve space on the page.

Return ONLY valid JSON with this exact structure:
{
  "experience": [
    {"index": 0, "selected_bullets": [0, 2], "priority": 1}
  ],
  "projects": [
    {"index": 0, "selected_bullets": [0, 1, 2], "priority": 1}
  ],
  "project_order": [0, 2, 1],
  "skills_focus": ["React", "TypeScript", "Playwright"],
  "bold_phrases": ["React", "TypeScript", "responsive", "RESTful API"]
}

Rules:
- Optimize for a truthful one-page resume.
- Preserve the candidate's strongest evidence for the target role.
- Frontend/fullstack roles should usually keep the most relevant projects highly visible.
- For frontend/fullstack roles, prefer a shape close to: 3 bullets for each of the top 3 experience entries, 3 bullets for the strongest project, and 2 bullets each for the next 2 projects when the candidate has enough relevant evidence.
- Use bullet indices from the provided inventory. Never invent bullets.
- Prefer bullets that contain concrete scope, metrics, tooling, testing, architecture, performance, collaboration, or delivery evidence.
- Keep enough bullets for both recruiter scan quality and ATS keyword coverage.
- Aim to fill the one-page resume without leaving obvious unused whitespace at the bottom. Prefer adding another strong original bullet over leaving the page sparse.
- skills_focus should contain 10-18 concrete skills/terms to surface in the skills section.
- bold_phrases should contain the highest-value ATS/recruiter terms already supported by the candidate's resume or the tailored rewrites.
"""


def _job_family(job: Job) -> str:
    text = " ".join([job.title or "", job.description or ""]).lower()
    if any(term in text for term in FULLSTACK_ROLE_TERMS):
        return "frontend_fullstack"
    return "general"


def _job_keywords(job: Job) -> set[str]:
    tokens = re.findall(
        r"[A-Za-z][A-Za-z0-9.+#/-]{1,}",
        " ".join([job.title or "", job.company_name or "", job.description or ""]).lower(),
    )
    return {token for token in tokens if token not in STOPWORDS and len(token) > 2}


def _item_relevance_score(job_keywords: set[str], values: list[str]) -> int:
    haystack = " ".join(_clean(value).lower() for value in values if _clean(value))
    return sum(1 for keyword in job_keywords if keyword in haystack)


def _project_role_bonus(project: dict[str, Any], job: Job) -> int:
    if _job_family(job) != "frontend_fullstack":
        return 0

    values = " ".join([
        project.get("name", ""),
        project.get("description", ""),
        *(project.get("bullets") or []),
        *(project.get("technologies") or []),
    ]).lower()
    product_terms = (
        "react", "next.js", "typescript", "javascript", "html", "css", "frontend",
        "full-stack", "full stack", "node.js", "fastapi", "api", "streamlit",
        "ui", "workflow", "customer-facing", "observability", "testing",
    )
    return sum(1 for term in product_terms if term in values)


def _rank_projects(projects: list[dict], job: Job) -> list[dict]:
    job_keywords = _job_keywords(job)
    ranked: list[tuple[int, int, dict]] = []
    for index, project in enumerate(projects):
        values = [
            project.get("name", ""),
            project.get("description", ""),
            *(project.get("bullets") or []),
            *(project.get("technologies") or []),
        ]
        score = _item_relevance_score(job_keywords, values) + _project_role_bonus(project, job)
        ranked.append((index, score, project))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return [project for _, _, project in ranked]


def _preferred_section_limits(parsed: dict[str, Any], job: Job) -> tuple[list[int], list[int]]:
    experience = parsed.get("experience", []) or []
    projects = parsed.get("projects", []) or []
    if _job_family(job) == "frontend_fullstack" and len(experience) >= 3 and len(projects) >= 3:
        return [3, 3, 3], [3, 2, 2]
    return [2, 2, 1, 1], [3, 2, 2]


def _preferred_bullet_indices(bullets: list[str], limit: int, *, job: Job, section: str) -> list[int]:
    if not bullets or limit <= 0:
        return []
    if _job_family(job) == "frontend_fullstack" and section in {"experience", "projects"}:
        if section == "experience" and limit >= 3 and len(bullets) > 3:
            selected = [0, 1]
            remaining = bullets[2:]
            remaining_indices = _select_top_bullet_indices(remaining, _job_keywords(job), 1)
            for relative_index in remaining_indices:
                selected.append(relative_index + 2)
            return sorted(selected[:limit])
        return list(range(min(limit, len(bullets))))
    return _select_top_bullet_indices(bullets, _job_keywords(job), min(limit, len(bullets)))


def _target_bullet_count(parsed: dict[str, Any], job: Job) -> int:
    experience_limits, project_limits = _preferred_section_limits(parsed, job)
    max_bullets = min(len(parsed.get("experience", []) or []), len(experience_limits))
    max_project_bullets = min(len(parsed.get("projects", []) or []), len(project_limits))
    if _job_family(job) == "frontend_fullstack" and max_bullets >= 3 and max_project_bullets >= 3:
        return 16
    return 18


def _preferred_skills_focus(parsed: dict[str, Any], job: Job, tailored: TailoredResume) -> list[str]:
    base = []
    if _job_family(job) == "frontend_fullstack":
        base.extend(FULLSTACK_RELEVANT_SKILLS)
    base.extend(tailored.skills_to_emphasize or [])
    base.extend(tailored.keywords_to_add or [])
    base.extend(tailored.skills_to_add or [])
    base.extend(parsed.get("skills") or [])
    return _merge_unique(base)[:18]


def _layout_profile(experience: list[dict], projects: list[dict], certificates: list[str]) -> tuple[str, str, str]:
    """Pick font size, line height, and line spread to fill one US Letter page.

    Density is the rough number of vertical lines we expect: bullets across
    experience + projects + certificates. We grow the font for sparse content so
    the page does not leave a trailing whitespace band, and we shrink for dense
    content so the artifact does not overflow to a second page.
    """
    density = sum(
        len(item.get("selected_bullets") or item.get("bullets") or _split_description_bullets(item.get("description")))
        for item in experience
    )
    density += sum(
        len(item.get("selected_bullets") or item.get("bullets") or _split_project_bullets(item.get("description")))
        for item in projects
    )
    density += len(certificates)
    if density >= 24:
        return "7.6pt", "8.2pt", "0.86"
    if density >= 21:
        return "7.9pt", "8.5pt", "0.88"
    if density >= 18:
        return "8.3pt", "9.1pt", "0.91"
    if density >= 15:
        return "8.7pt", "9.6pt", "0.94"
    if density >= 12:
        return "9.1pt", "10.1pt", "0.97"
    if density >= 9:
        return "9.6pt", "10.7pt", "1.0"
    return "10.0pt", "11.2pt", "1.05"


def _select_top_bullet_indices(bullets: list[str], job_keywords: set[str], limit: int) -> list[int]:
    if not bullets or limit <= 0:
        return []
    scored: list[tuple[int, int, int]] = []
    for index, bullet in enumerate(bullets):
        score = _item_relevance_score(job_keywords, [bullet])
        score += len(_metric_tokens(bullet))
        score += max(0, 4 - index)
        scored.append((index, score, len(_clean(bullet))))
    scored.sort(key=lambda item: (-item[1], -item[2], item[0]))
    selected = sorted(index for index, _, _ in scored[:limit])
    return selected


def _default_artifact_plan(parsed: dict[str, Any], job: Job, tailored: TailoredResume) -> dict[str, Any]:
    experience = parsed.get("experience", []) or []
    projects = _rank_projects(parsed.get("projects", []) or [], job)
    experience_limits, project_limits = _preferred_section_limits(parsed, job)

    experience_plan: list[dict[str, Any]] = []
    for index, item in enumerate(experience[: len(experience_limits)]):
        bullets = item.get("bullets") or _split_description_bullets(item.get("description"))
        limit = experience_limits[index]
        selected = _preferred_bullet_indices(bullets, limit, job=job, section="experience")
        if selected:
            experience_plan.append({"index": index, "selected_bullets": selected, "priority": index + 1})

    project_order: list[int] = []
    projects_plan: list[dict[str, Any]] = []
    original_projects = parsed.get("projects", []) or []
    for ordered_priority, ranked_project in enumerate(projects[: len(project_limits)], start=1):
        try:
            original_index = next(
                idx for idx, project in enumerate(original_projects)
                if _clean(project.get("name")).lower() == _clean(ranked_project.get("name")).lower()
            )
        except StopIteration:
            continue
        project_order.append(original_index)
        bullets = ranked_project.get("bullets") or _split_project_bullets(ranked_project.get("description"))
        limit = project_limits[ordered_priority - 1]
        selected = _preferred_bullet_indices(bullets, limit, job=job, section="projects")
        if selected:
            projects_plan.append({"index": original_index, "selected_bullets": selected, "priority": ordered_priority})

    skills_focus = _preferred_skills_focus(parsed, job, tailored)

    return {
        "experience": experience_plan,
        "projects": projects_plan,
        "project_order": project_order,
        "skills_focus": skills_focus,
        "bold_phrases": _merge_unique([
            *(tailored.skills_to_emphasize or []),
            *(tailored.keywords_to_add or []),
            *(tailored.skills_to_add or []),
        ])[:16],
    }


def _count_selected_bullets(plan: dict[str, Any]) -> int:
    total = 0
    for section in ("experience", "projects"):
        for item in plan.get(section, []) or []:
            total += len(item.get("selected_bullets") or [])
    return total


def _expand_plan_to_fill_page(parsed: dict[str, Any], job: Job, plan: dict[str, Any]) -> dict[str, Any]:
    target_bullets = _target_bullet_count(parsed, job)
    current_total = _count_selected_bullets(plan)
    if current_total >= target_bullets:
        return plan

    job_keywords = _job_keywords(job)
    experience_lookup = {
        item["index"]: item
        for item in (plan.get("experience") or [])
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }
    project_lookup = {
        item["index"]: item
        for item in (plan.get("projects") or [])
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }

    candidates: list[tuple[str, int, int, int, int]] = []
    for idx, item in enumerate((parsed.get("experience") or [])[:4]):
        bullets = item.get("bullets") or _split_description_bullets(item.get("description"))
        selected = set((experience_lookup.get(idx) or {}).get("selected_bullets") or [])
        for bullet_index, bullet in enumerate(bullets):
            if bullet_index in selected:
                continue
            score = _item_relevance_score(job_keywords, [bullet]) + len(_metric_tokens(bullet))
            priority = idx
            candidates.append(("experience", idx, bullet_index, score, priority))

    for idx, item in enumerate((parsed.get("projects") or [])[:3]):
        bullets = item.get("bullets") or _split_project_bullets(item.get("description"))
        selected = set((project_lookup.get(idx) or {}).get("selected_bullets") or [])
        for bullet_index, bullet in enumerate(bullets):
            if bullet_index in selected:
                continue
            score = _item_relevance_score(job_keywords, [bullet]) + len(_metric_tokens(bullet))
            priority = idx
            candidates.append(("projects", idx, bullet_index, score + 1, priority))

    candidates.sort(key=lambda item: (-item[3], item[4], item[2]))

    for section_name, idx, bullet_index, _, _ in candidates:
        if current_total >= target_bullets:
            break
        lookup = experience_lookup if section_name == "experience" else project_lookup
        if idx not in lookup:
            lookup[idx] = {"index": idx, "selected_bullets": [], "priority": idx + 1}
            (plan["experience"] if section_name == "experience" else plan["projects"]).append(lookup[idx])
        selected = lookup[idx].setdefault("selected_bullets", [])
        if bullet_index not in selected:
            selected.append(bullet_index)
            selected.sort()
            current_total += 1

    return plan


def _build_artifact_plan_prompt(parsed: dict[str, Any], job: Job, tailored: TailoredResume) -> str:
    parts = [
        f"TARGET ROLE: {job.title} at {job.company_name}",
        f"JOB DESCRIPTION:\n{job.description or ''}",
        "",
        f"JOB FAMILY: {_job_family(job)}",
        f"PREFERRED BULLET TARGET: {_target_bullet_count(parsed, job)}",
        "",
        "EXPERIENCE BULLETS:",
    ]
    for index, item in enumerate((parsed.get("experience") or [])[:4]):
        parts.append(f"[experience:{index}] {item.get('title', '')} at {item.get('company', '')}")
        bullets = item.get("bullets") or _split_description_bullets(item.get("description"))
        for bullet_index, bullet in enumerate(bullets):
            parts.append(f"  ({bullet_index}) {bullet}")

    parts.extend(["", "PROJECT BULLETS:"])
    for index, item in enumerate((parsed.get("projects") or [])[:3]):
        parts.append(f"[projects:{index}] {item.get('name', '')}")
        bullets = item.get("bullets") or _split_project_bullets(item.get("description"))
        for bullet_index, bullet in enumerate(bullets):
            parts.append(f"  ({bullet_index}) {bullet}")

    parts.extend([
        "",
        f"TAILORED SKILLS TO EMPHASIZE: {', '.join(tailored.skills_to_emphasize or [])}",
        f"TAILORED SKILLS TO ADD: {', '.join(tailored.skills_to_add or [])}",
        f"TAILORED KEYWORDS TO ADD: {', '.join(tailored.keywords_to_add or [])}",
        f"PREFERRED RELEVANT SKILLS LINE: {', '.join(_preferred_skills_focus(parsed, job, tailored))}",
    ])
    return "\n".join(parts)


async def _build_resume_artifact_plan(
    *,
    parsed: dict[str, Any],
    job: Job,
    tailored: TailoredResume,
) -> dict[str, Any]:
    fallback = _expand_plan_to_fill_page(parsed, job, _default_artifact_plan(parsed, job, tailored))
    if not job.description:
        return fallback

    try:
        result = await generate_message(
            system_prompt=ARTIFACT_PLAN_SYSTEM_PROMPT,
            user_prompt=_build_artifact_plan_prompt(parsed, job, tailored),
            max_tokens=1400,
        )
        raw = result.get("draft", "")
        if raw.startswith("```"):
            lines = [line for line in raw.split("\n") if not line.strip().startswith("```")]
            raw = "\n".join(lines)
        parsed_plan = json.loads(raw)
        if not isinstance(parsed_plan, dict):
            return fallback
        planned = {
            "experience": parsed_plan.get("experience") or fallback["experience"],
            "projects": parsed_plan.get("projects") or fallback["projects"],
            "project_order": parsed_plan.get("project_order") or fallback["project_order"],
            "skills_focus": parsed_plan.get("skills_focus") or fallback["skills_focus"],
            "bold_phrases": parsed_plan.get("bold_phrases") or fallback["bold_phrases"],
        }
        if _job_family(job) == "frontend_fullstack":
            planned["experience"] = fallback["experience"]
            planned["projects"] = fallback["projects"]
            planned["project_order"] = fallback["project_order"]
        return _expand_plan_to_fill_page(parsed, job, planned)
    except Exception as exc:
        logger.warning("Falling back to deterministic artifact plan: %s", exc)
        return fallback


def _emphasis_terms(job: Job, tailored: TailoredResume) -> list[str]:
    job_terms = re.findall(
        r"(?:ReactJS|React|JavaScript|TypeScript|HTML5?|CSS3?|Node\.js|Playwright|Cypress|WCAG|CI/CD|telemetry|"
        r"experimentation|personalization|responsive|accessible|internationalized|RESTful APIs?|Git|cross-functional|"
        r"component-based|components?)",
        " ".join([job.title or "", job.description or ""]),
        flags=re.IGNORECASE,
    )
    return _merge_unique([
        *(tailored.skills_to_emphasize or []),
        *(tailored.keywords_to_add or []),
        *(tailored.skills_to_add or []),
        *job_terms,
        *DEFAULT_EMPHASIS_TERMS,
    ])


def _latex_rich_text(text: str | None, emphasis_terms: list[str]) -> str:
    raw = _clean(text)
    if not raw:
        return ""

    spans: list[tuple[int, int]] = []

    def _has_overlap(start: int, end: int) -> bool:
        return any(start < existing_end and end > existing_start for existing_start, existing_end in spans)

    for start, end in _quantifiable_measure_spans(raw):
        if not _has_overlap(start, end):
            spans.append((start, end))

    ordered_terms = sorted(
        {term for term in emphasis_terms if _clean(term)},
        key=lambda term: len(_clean(term)),
        reverse=True,
    )

    for index, term in enumerate(ordered_terms):
        clean_term = _clean(term)
        if not clean_term:
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9])({re.escape(clean_term)})(?![A-Za-z0-9])", re.IGNORECASE)
        for match in pattern.finditer(raw):
            start, end = match.span(1)
            if not _has_overlap(start, end):
                spans.append((start, end))

    if not spans:
        return _latex_escape(raw)

    rendered: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        rendered.append(_latex_escape_preserving_spacing(raw[cursor:start]))
        rendered.append(
            rf"\textbf{{{_latex_escape_preserving_spacing(raw[start:end])}}}"
        )
        cursor = end
    rendered.append(_latex_escape_preserving_spacing(raw[cursor:]))
    return "".join(rendered)


def _format_skill_items(skills: list[str], emphasis_terms: list[str]) -> str:
    return ", ".join(_latex_rich_text(skill, emphasis_terms) for skill in skills if _clean(skill))


def _render_resume_latex(
    *,
    profile: Profile,
    user: User | None,
    job: Job,
    tailored: TailoredResume,
    artifact_plan: dict[str, Any] | None = None,
    rewrite_decisions: dict[str, str] | None = None,
    auto_accept_inferred: bool = False,
) -> str:
    parsed = _extract_resume_data(profile)
    contact = parsed.get("contact") or {}
    artifact_plan = artifact_plan or _default_artifact_plan(parsed, job, tailored)
    projects = parsed.get("projects", []) or []
    project_technologies = [
        technology
        for project in projects
        for technology in (project.get("technologies") or [])
    ]
    skills = _ordered_skills(
        parsed.get("skills", []) or [],
        tailored.skills_to_emphasize or [],
        tailored.skills_to_add or [],
        tailored.keywords_to_add or [],
        project_technologies,
    )
    skill_categories = parsed.get("skills_by_category") or {}
    base_languages = skill_categories.get("Languages", [])
    base_technologies = skill_categories.get("Technologies", [])
    base_methodologies = skill_categories.get("Methodologies", [])
    extra_languages, extra_technologies, extra_methodologies = _categorize_skills([
        skill for skill in skills
        if _clean(skill).lower() not in {
            *[_clean(item).lower() for item in base_languages],
            *[_clean(item).lower() for item in base_technologies],
            *[_clean(item).lower() for item in base_methodologies],
        }
    ])
    languages = _merge_unique([*base_languages, *extra_languages])
    technologies = _merge_unique([*base_technologies, *extra_technologies])
    methodologies = _merge_unique([*base_methodologies, *extra_methodologies])
    experience = parsed.get("experience", []) or []
    education = parsed.get("education", []) or []
    certificates = parsed.get("certificates", []) or []
    address = _clean(contact.get("address")) or _clean((profile.target_locations or [None])[0])
    phone = _clean(contact.get("phone")) or _extract_phone(profile.resume_raw)
    email = _clean(contact.get("email")) or (user.email if user else None)
    linkedin_url = _find_contact_url(profile, contact, "linkedin.com")
    github_url = _find_contact_url(profile, contact, "github.com")
    portfolio_url = profile.portfolio_url
    emphasis_terms = _emphasis_terms(job, tailored)
    emphasis_terms = _merge_unique([*(artifact_plan.get("bold_phrases") or []), *emphasis_terms])

    active_rewrites = _filter_rewrites_by_decisions(
        tailored.bullet_rewrites,
        rewrite_decisions,
        auto_accept_inferred=auto_accept_inferred,
    )
    experience_rewrites_by_index = _index_rewrites(
        active_rewrites,
        section_name="experience",
        index_field="experience_index",
    )
    project_rewrites_by_index = _index_rewrites(
        active_rewrites,
        section_name="projects",
        index_field="project_index",
    )

    experience_budget = {
        int(item["index"]): item.get("selected_bullets", [])
        for item in (artifact_plan.get("experience") or [])
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }
    project_budget = {
        int(item["index"]): item.get("selected_bullets", [])
        for item in (artifact_plan.get("projects") or [])
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }

    experience_limits, project_limits = _preferred_section_limits(parsed, job)
    planned_experience: list[dict[str, Any]] = []
    for idx, item in enumerate(experience[:4]):
        original_bullets = item.get("bullets") or _split_description_bullets(item.get("description"))
        budget_default = experience_limits[idx] if idx < len(experience_limits) else 1
        fallback_indices = _preferred_bullet_indices(
            original_bullets,
            min(budget_default, len(original_bullets)),
            job=job,
            section="experience",
        )
        selected_indices = experience_budget.get(idx) or fallback_indices
        selected_bullets = [
            original_bullets[bullet_index]
            for bullet_index in selected_indices
            if isinstance(bullet_index, int) and 0 <= bullet_index < len(original_bullets)
        ]
        selected_bullets = _apply_bullet_rewrites(selected_bullets, experience_rewrites_by_index.get(idx, []))
        if selected_bullets:
            planned_experience.append({**item, "selected_bullets": selected_bullets})

    ranked_projects = _rank_projects(projects, job)
    original_project_lookup = {
        _clean(project.get("name")).lower(): idx
        for idx, project in enumerate(projects)
    }
    default_project_order = [
        original_project_lookup.get(_clean(project.get("name")).lower())
        for project in ranked_projects[:3]
        if original_project_lookup.get(_clean(project.get("name")).lower()) is not None
    ]
    project_order = [
        idx for idx in (artifact_plan.get("project_order") or default_project_order)
        if isinstance(idx, int) and 0 <= idx < len(projects)
    ]
    if not project_order:
        project_order = default_project_order

    planned_projects: list[dict[str, Any]] = []
    for idx in project_order:
        if len(planned_projects) >= 3:
            break
        project = projects[idx]
        if not _is_valid_project_name(project.get("name")):
            continue
        ordered_priority = len(planned_projects)
        original_bullets = project.get("bullets") or _split_project_bullets(project.get("description"))
        budget_default = project_limits[ordered_priority] if ordered_priority < len(project_limits) else 2
        fallback_indices = _preferred_bullet_indices(
            original_bullets,
            min(budget_default, len(original_bullets)),
            job=job,
            section="projects",
        )
        selected_indices = project_budget.get(idx) or fallback_indices
        selected_bullets = [
            original_bullets[bullet_index]
            for bullet_index in selected_indices
            if isinstance(bullet_index, int) and 0 <= bullet_index < len(original_bullets)
        ]
        selected_bullets = _apply_bullet_rewrites(selected_bullets, project_rewrites_by_index.get(idx, []))
        if selected_bullets:
            planned_projects.append({**project, "selected_bullets": selected_bullets})

    font_size, line_height, line_spread = _layout_profile(planned_experience, planned_projects, certificates)
    focused_skills = _merge_unique([
        *(artifact_plan.get("skills_focus") or []),
        *(tailored.skills_to_emphasize or []),
        *(tailored.keywords_to_add or []),
        *(tailored.skills_to_add or []),
        *(_preferred_skills_focus(parsed, job, tailored) or []),
    ])[:18]

    contact_parts: list[str] = []
    if address:
        contact_parts.append(_latex_escape(address))
    if phone:
        phone_url = re.sub(r"\D", "", phone)
        contact_parts.append(rf"\href{{tel:{phone_url}}}{{{_latex_escape(phone)}}}")
    if email:
        contact_parts.append(rf"\href{{mailto:{_latex_url(email)}}}{{{_latex_escape(email)}}}")
    if linkedin_url:
        contact_parts.append(rf"\url{{{_latex_url(linkedin_url)}}}")
    if github_url:
        contact_parts.append(rf"\url{{{_latex_url(github_url)}}}")
    if portfolio_url:
        contact_parts.append(rf"\url{{{_latex_url(portfolio_url)}}}")

    lines: list[str] = [
        r"\documentclass[letterpaper]{article}",
        r"\usepackage[margin=0.5in]{geometry}",
        r"\usepackage{multicol}",
        r"\usepackage{enumitem}",
        r"\usepackage{setspace}",
        r"\usepackage{parskip}",
        r"\usepackage{hyperref}",
        r"\hypersetup{colorlinks=true,urlcolor=blue}",
        r"\usepackage{anyfontsize}",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\parskip}{0pt}",
        r"\setlist[itemize]{noitemsep, topsep=0pt, leftmargin=*}",
        r"\pagestyle{empty}",
        r"\renewcommand{\thepage}{}",
        r"\pagenumbering{gobble}",
        r"\begin{document}",
        r"\thispagestyle{empty}",
        rf"\fontsize{{{font_size}}}{{{line_height}}}\selectfont",
        rf"\linespread{{{line_spread}}}",
        r"\begin{center}",
        rf"  \textbf{{\Huge \scshape {_latex_escape(profile.full_name) or 'Candidate Name'}}} \\ \vspace{{3pt}}",
        r"  \small",
    ]

    if contact_parts:
        lines.append("  " + "\n  $|$\n  ".join(contact_parts))
    lines.extend([
        r"\end{center}",
        r"\vspace{-0.1in}",
    ])

    if education:
        lines.extend([
            r"\subsection*{Education}",
            r"\hrule",
            r"\vspace{0.1in}",
        ])
        for item in education[:2]:
            institution = _latex_escape(item.get("institution")) or "Institution"
            degree = _latex_escape(item.get("degree"))
            field = _latex_escape(item.get("field"))
            location_label = _latex_escape(item.get("location"))
            grad = _latex_escape(item.get("graduation_date"))
            degree_line = degree or field
            details = [detail for detail in (item.get("details") or []) if _clean(detail)]

            lines.append(rf"\textbf{{{institution}}} \hfill \textbf{{{grad}}}\\")
            if degree_line or location_label:
                lines.append(rf"\textit{{{degree_line}}} \hfill {location_label}\\")
            for detail in details[:2]:
                lines.append(rf"{_latex_escape(detail)}\\")
            lines.append("")
        lines.append(r"\vspace{-0.15in}")

    if planned_experience:
        lines.extend([
            r"\subsection*{Experience}",
            r"\hrule",
            r"\vspace{0.05in}",
        ])
        for item in planned_experience:
            company = _latex_escape(item.get("company")) or "Company"
            title = _latex_escape(item.get("title")) or "Role"
            start = _latex_escape(item.get("start_date"))
            end = _latex_escape(item.get("end_date")) or "Present"
            location_label = _latex_escape(item.get("location"))
            bullets = item.get("selected_bullets") or []

            lines.append(rf"\textbf{{{company}}} \hfill \textbf{{{start} -- {end}}}\\")
            lines.append(rf"\textit{{{title}}} \hfill {location_label}")
            lines.append(r"\vspace{0.05in}")
            lines.append(r"\begin{itemize}")
            for bullet in bullets[:4]:
                lines.append(rf"\item {_latex_rich_text(bullet, emphasis_terms)}")
            lines.append(r"\end{itemize}")
            lines.append(r"\vspace{0.04in}")

    if planned_projects:
        lines.extend([
            r"\vspace{-0.08in}",
            r"\subsection*{Projects}",
            r"\hrule",
            r"\vspace{0.05in}",
        ])
        for project in planned_projects:
            name = _latex_escape(project.get("name")) or "Project"
            url = _derive_project_url(project, profile, contact)
            label_source = project.get("link_label") or (f"GitHub: {project.get('name')}" if url else "")
            link_label = _latex_escape(label_source)
            heading = rf"\textbf{{{name}}}"
            if url and link_label:
                heading += rf" (\href{{{_latex_url(url)}}}{{{link_label}}})"
            elif link_label:
                heading += rf" ({link_label})"
            lines.append(heading)
            lines.append(r"\begin{itemize}")
            project_bullets = project.get("selected_bullets") or [project.get("description") or ""]
            for bullet in project_bullets[:3]:
                lines.append(rf"\item {_latex_rich_text(bullet, emphasis_terms)}")
            lines.append(r"\end{itemize}")
            lines.append(r"\vspace{0.02in}")

    if languages or technologies or methodologies:
        focused_lower = {_clean(s).lower() for s in focused_skills}
        languages_out = [s for s in languages if _clean(s).lower() not in focused_lower]
        technologies_out = [s for s in technologies if _clean(s).lower() not in focused_lower]
        methodologies_out = [s for s in methodologies if _clean(s).lower() not in focused_lower]
        lines.extend([
            r"\vspace{-0.08in}",
            r"\subsection*{Technical Skills}",
            r"\hrule",
            r"\vspace{0.05in}",
            r"\begin{itemize}[leftmargin=*]",
        ])
        if focused_skills:
            lines.append(rf"\item \textbf{{Relevant}}: {_format_skill_items(focused_skills, emphasis_terms)}")
        if languages_out:
            lines.append(rf"\item \textbf{{Languages}}: {_format_skill_items(languages_out, emphasis_terms)}")
        if technologies_out:
            lines.append(rf"\item \textbf{{Technologies}}: {_format_skill_items(technologies_out, emphasis_terms)}")
        if methodologies_out:
            lines.append(rf"\item \textbf{{Methodologies}}: {_format_skill_items(methodologies_out, emphasis_terms)}")
        lines.append(r"\end{itemize}")

    if certificates:
        lines.extend([
            r"\vspace{-0.08in}",
            r"\subsection*{Certificates}",
            r"\hrule",
            r"\vspace{0.08in}",
            r"\begin{itemize}[leftmargin=*]",
        ])
        for certificate in certificates[:4]:
            lines.append(rf"\item {_latex_escape(certificate)}")
        lines.append(r"\end{itemize}")

    lines.extend([
        r"\vspace{-0.05in}",
        r"\end{document}",
    ])

    return "\n".join(lines) + "\n"


def render_resume_artifact_pdf(content: str) -> bytes:
    """Compile LaTeX resume artifact content into PDF bytes."""
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        raise ValueError("pdflatex is not installed in the current environment.")

    with tempfile.TemporaryDirectory(prefix="resume-artifact-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        tex_path = tmp_path / "resume.tex"
        pdf_path = tmp_path / "resume.pdf"
        tex_path.write_text(content, encoding="utf-8")

        command = [
            pdflatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(tmp_path),
            str(tex_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not pdf_path.exists():
            raise ValueError(
                "Failed to compile LaTeX resume artifact to PDF."
                f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

        return pdf_path.read_bytes()


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


def _latex_plain_text(line: str) -> str:
    text = _clean(line)
    substitutions = [
        (re.compile(r"\\href\{[^{}]*\}\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\url\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\textbf\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\textit\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\hl\{([^{}]*)\}"), r"\1"),
        (re.compile(r"\\sout\{([^{}]*)\}"), r"\1"),
    ]
    previous = ""
    while previous != text:
        previous = text
        for pattern, replacement in substitutions:
            text = pattern.sub(replacement, text)
    text = re.sub(r"^\\item\s*", " ", text)
    text = text.replace(r"\\", " ")
    text = re.sub(r"\\([&%$#_{}])", r"\1", text)
    text = re.sub(r"\\textbackslash\{\}", r"\\", text)
    text = re.sub(r"\\[a-zA-Z*]+(?:\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return _clean(text)


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


def _latex_escape_preserving_spacing(value: str | None) -> str:
    text = value or ""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("—", "-").replace("–", "-").replace("•", "-")
    return text


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


async def _load_or_generate_tailoring(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job: Job,
    profile: Profile,
    prefer_existing: bool = True,
) -> TailoredResume:
    if prefer_existing:
        existing_result = await db.execute(
            select(TailoredResume)
            .where(
                TailoredResume.user_id == user_id,
                TailoredResume.job_id == job.id,
            )
            .order_by(TailoredResume.created_at.desc())
            .limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            existing.bullet_rewrites = _normalize_bullet_rewrites(existing.bullet_rewrites or [])
            return existing

    job_data = {
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "description": job.description,
        "remote": job.remote,
        "experience_level": job.experience_level,
    }
    score, breakdown = score_job(job_data, profile)
    suggestions = await tailor_resume(job_data, profile, score, breakdown)

    tailored = TailoredResume(
        user_id=user_id,
        job_id=job.id,
        summary=suggestions.get("summary"),
        skills_to_emphasize=suggestions.get("skills_to_emphasize"),
        skills_to_add=suggestions.get("skills_to_add"),
        keywords_to_add=suggestions.get("keywords_to_add"),
        bullet_rewrites=suggestions.get("bullet_rewrites"),
        section_suggestions=suggestions.get("section_suggestions"),
        overall_strategy=suggestions.get("overall_strategy"),
        model=suggestions.get("model"),
        provider=suggestions.get("provider"),
    )
    db.add(tailored)
    await db.commit()
    await db.refresh(tailored)
    return tailored


async def generate_resume_artifact_for_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    rewrite_decisions: dict[str, str] | None = None,
    reuse_decisions: bool = True,
) -> ResumeArtifact:
    job_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not (profile.resume_parsed or profile.resume_raw):
        raise ValueError("Upload a resume in your profile first to generate a resume artifact.")

    enriched_resume = _extract_resume_data(profile)
    if enriched_resume != (profile.resume_parsed or {}):
        profile.resume_parsed = enriched_resume

    user_result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = user_result.scalar_one_or_none()

    tailored = await _load_or_generate_tailoring(
        db,
        user_id=user_id,
        job=job,
        profile=profile,
        prefer_existing=False,
    )
    artifact_plan = await _build_resume_artifact_plan(
        parsed=enriched_resume,
        job=job,
        tailored=tailored,
    )

    filename = f"resume-{_slugify_label(job.company_name, 'company')}-{datetime.now(timezone.utc).date().isoformat()}.tex"

    artifact_result = await db.execute(
        select(ResumeArtifact).where(
            ResumeArtifact.user_id == user_id,
            ResumeArtifact.job_id == job_id,
        )
    )
    artifact = artifact_result.scalar_one_or_none()

    if artifact is None:
        artifact = ResumeArtifact(
            user_id=user_id,
            job_id=job_id,
        )
        db.add(artifact)

    if rewrite_decisions is not None:
        decisions = dict(rewrite_decisions)
    elif reuse_decisions and artifact.rewrite_decisions:
        decisions = dict(artifact.rewrite_decisions)
    else:
        decisions = {}

    auto_accept = bool(getattr(profile, "resume_auto_accept_inferred", False))
    content = _render_resume_latex(
        profile=profile,
        user=user,
        job=job,
        tailored=tailored,
        artifact_plan=artifact_plan,
        rewrite_decisions=decisions,
        auto_accept_inferred=auto_accept,
    )

    artifact.tailored_resume_id = tailored.id
    artifact.format = "latex"
    artifact.filename = filename
    artifact.content = content
    artifact.rewrite_decisions = decisions
    artifact.generated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(artifact)
    return artifact


async def get_resume_artifact_for_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> ResumeArtifact | None:
    result = await db.execute(
        select(ResumeArtifact).where(
            ResumeArtifact.user_id == user_id,
            ResumeArtifact.job_id == job_id,
        )
    )
    return result.scalar_one_or_none()


async def list_resume_artifacts_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int | None = None,
) -> list[tuple[ResumeArtifact, Job]]:
    stmt = (
        select(ResumeArtifact, Job)
        .join(Job, Job.id == ResumeArtifact.job_id)
        .where(ResumeArtifact.user_id == user_id)
        .order_by(ResumeArtifact.generated_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.all())
