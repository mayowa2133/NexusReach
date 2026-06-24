"""Deterministic, explainable quality evaluation for generated resumes.

The early-career technical profile adapts the public category balance from
HackerRank's MIT-licensed ``interviewstreet/hiring-agent`` project.  The
evaluator intentionally does not claim to reproduce an employer's ATS: it
scores only supported resume evidence and the generated artifact for the
specific NexusReach job.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services.match_scoring import _estimate_user_years
from app.services.occupation_taxonomy import (
    classify_title,
    is_engineering_flavored,
    occupation_keys_from_tags,
)
from app.services.resume_artifact.textnorm import _latex_plain_text, _metric_tokens
from app.services.resume_tailor import extract_jd_must_surface


RUBRIC_VERSION = "nexusreach_resume_quality_v1"
EVALUATION_MODE = "deterministic_supported_evidence"
SOURCE_ATTRIBUTION = {
    "name": "HackerRank Hiring Agent",
    "url": "https://github.com/interviewstreet/hiring-agent",
    "license": "MIT",
    "adaptation": (
        "HackerRank-inspired early-career category balance with NexusReach "
        "occupation-aware profiles, job-fit, parseability, and truthfulness gates."
    ),
}
DISCLAIMER = (
    "This is an explainable screening simulation based on the selected job and "
    "supported resume evidence. It is not an employer decision, rejection reason, "
    "or guarantee of an interview."
)


@dataclass(frozen=True)
class QualityCategoryDefinition:
    key: str
    label: str
    maximum: int


@dataclass(frozen=True)
class QualityProfile:
    key: str
    label: str
    categories: tuple[QualityCategoryDefinition, ...]


EARLY_CAREER_TECHNICAL = QualityProfile(
    key="early_career_technical_v1",
    label="Early-career technical",
    categories=(
        QualityCategoryDefinition("open_source", "Open-source contribution", 35),
        QualityCategoryDefinition("projects", "Projects", 30),
        QualityCategoryDefinition("production", "Production experience", 25),
        QualityCategoryDefinition("technical_skills", "Technical skills", 10),
    ),
)

EXPERIENCED_TECHNICAL = QualityProfile(
    key="experienced_technical_v1",
    label="Experienced technical",
    categories=(
        QualityCategoryDefinition("production", "Production impact", 45),
        QualityCategoryDefinition("projects", "Technical projects", 20),
        QualityCategoryDefinition("technical_skills", "Technical depth", 20),
        QualityCategoryDefinition("open_source", "Open-source contribution", 15),
    ),
)

GENERAL_PROFESSIONAL = QualityProfile(
    key="general_professional_v1",
    label="General professional",
    categories=(
        QualityCategoryDefinition("outcomes", "Demonstrated outcomes", 35),
        QualityCategoryDefinition("role_experience", "Role-relevant experience", 35),
        QualityCategoryDefinition("capabilities", "Professional capabilities", 20),
        QualityCategoryDefinition("supporting_evidence", "Supporting evidence", 10),
    ),
)

QUALITY_PROFILES: dict[str, QualityProfile] = {
    profile.key: profile
    for profile in (
        EARLY_CAREER_TECHNICAL,
        EXPERIENCED_TECHNICAL,
        GENERAL_PROFESSIONAL,
    )
}


_SENIOR_TERMS = re.compile(
    r"\b(?:senior|staff|principal|lead|manager|director|head|vp|vice president|chief)\b",
    re.IGNORECASE,
)
_EARLY_TERMS = re.compile(
    r"\b(?:intern|internship|new grad|graduate|entry[- ]level|junior|associate)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s{}]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
_OPEN_SOURCE_RE = re.compile(
    r"\b(?:open[ -]source|pull requests?|merged\s+prs?|github contributions?|"
    r"contribut(?:ed|ion|ions|or)\s+to\s+(?:an?\s+|the\s+)?(?:public\s+)?"
    r"(?:repository|repo|open[ -]source project)|google summer of code|\bgsoc\b)\b",
    re.IGNORECASE,
)
_COMPLEXITY_RE = re.compile(
    r"\b(?:architecture|distributed|microservices?|real[- ]time|machine learning|"
    r"artificial intelligence|\bai\b|authentication|database|pipeline|orchestration|"
    r"serverless|full[- ]stack|mobile|native|infrastructure|automation|api)\b",
    re.IGNORECASE,
)
_PRODUCTION_RE = re.compile(
    r"\b(?:production|deployed|launched|shipped|released|customers?|users?|availability|"
    r"reliability|monitoring|on[- ]call|operational|scaled?|revenue|cost|compliance)\b",
    re.IGNORECASE,
)
_OUTCOME_RE = re.compile(
    r"\b(?:improved|increased|reduced|decreased|saved|grew|delivered|enabled|"
    r"accelerated|automated|launched|shipped|achieved|supported|managed|led)\b",
    re.IGNORECASE,
)
_GENERIC_PROJECT_RE = re.compile(
    r"\b(?:todo|to-do|calculator|weather app|note[- ]taking|recipe app|"
    r"hello world|tutorial|basic crud|portfolio website)\b",
    re.IGNORECASE,
)
_JOB_STOPWORDS = {
    "about", "after", "also", "and", "are", "because", "been", "being", "but",
    "can", "company", "from", "have", "into", "job", "more", "must", "our",
    "role", "that", "the", "their", "them", "they", "this", "through", "using",
    "what", "when", "where", "which", "will", "with", "work", "would", "years",
    "your", "you", "responsibilities", "requirements", "preferred", "required",
}


def _bounded(value: float, maximum: float) -> float:
    return round(max(0.0, min(float(maximum), float(value))), 1)


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _entry_bullets(entry: dict[str, Any]) -> list[str]:
    bullets = [_text(item) for item in _list(entry.get("bullets")) if _text(item)]
    if bullets:
        return bullets
    description = _text(entry.get("description"))
    return [description] if description else []


def _entry_text(entry: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("name", "title", "company", "description", "link_label", "url"):
        if _text(entry.get(key)):
            values.append(_text(entry.get(key)))
    values.extend(_entry_bullets(entry))
    values.extend(_text(value) for value in _list(entry.get("technologies")) if _text(value))
    return " ".join(values)


def _supported_source_text(parsed: dict[str, Any]) -> str:
    """Return only role evidence; intentionally exclude demographic/grade data."""
    parts: list[str] = []
    for entry in _list(parsed.get("experience")):
        if isinstance(entry, dict):
            parts.append(_entry_text(entry))
    for entry in _list(parsed.get("projects")):
        if isinstance(entry, dict):
            parts.append(_entry_text(entry))
    parts.extend(_text(skill) for skill in _list(parsed.get("skills")) if _text(skill))
    for values in _dict(parsed.get("skills_by_category")).values():
        parts.extend(_text(skill) for skill in _list(values) if _text(skill))
    parts.extend(_text(item) for item in _list(parsed.get("certificates")) if _text(item))
    return "\n".join(parts)


def _contains_entry(rendered_text: str, entry: dict[str, Any]) -> bool:
    rendered = rendered_text.lower()
    identity = _text(entry.get("name") or entry.get("company") or entry.get("title")).lower()
    if identity and identity in rendered:
        return True
    for bullet in _entry_bullets(entry):
        tokens = [token for token in re.findall(r"[a-z0-9+#.]+", bullet.lower()) if len(token) > 4]
        if tokens and sum(token in rendered for token in tokens[:8]) >= min(3, len(tokens)):
            return True
    return False


def _occupation_keys(job: object) -> list[str]:
    tags = getattr(job, "tags", None)
    keys = occupation_keys_from_tags(tags if isinstance(tags, list) else None)
    if keys:
        return keys
    return classify_title(
        _text(getattr(job, "title", "")),
        _text(getattr(job, "description", "")),
    )


def select_quality_profile(parsed: dict[str, Any], job: object) -> QualityProfile:
    """Select a deterministic occupation/seniority rubric for one job."""
    keys = _occupation_keys(job)
    department = _text(getattr(job, "department", "")) or None
    if not is_engineering_flavored(keys, department=department):
        return GENERAL_PROFESSIONAL

    job_text = " ".join(
        [
            _text(getattr(job, "title", "")),
            _text(getattr(job, "experience_level", "")),
        ]
    )
    if _EARLY_TERMS.search(job_text):
        return EARLY_CAREER_TECHNICAL
    if _SENIOR_TERMS.search(job_text):
        return EXPERIENCED_TECHNICAL

    years = _estimate_user_years(
        [entry for entry in _list(parsed.get("experience")) if isinstance(entry, dict)]
    )
    return EARLY_CAREER_TECHNICAL if years < 3.0 else EXPERIENCED_TECHNICAL


def _job_terms(job: object) -> list[str]:
    description = _text(getattr(job, "description", ""))
    extracted = extract_jd_must_surface(description).get("must_surface") or []
    ordered = [
        _text(term)
        for term in extracted
        if _text(term)
        and re.search(
            rf"(?<![A-Za-z0-9]){re.escape(_text(term))}(?![A-Za-z0-9])",
            description,
            re.IGNORECASE,
        )
    ]

    title = _text(getattr(job, "title", ""))
    title_tokens = re.findall(r"[A-Za-z][A-Za-z0-9+#./-]{2,}", title)
    body_tokens = re.findall(r"[A-Za-z][A-Za-z0-9+#./-]{3,}", description)
    counts: dict[str, int] = {}
    original: dict[str, str] = {}
    for token in body_tokens:
        key = token.lower().strip("./-")
        if key in _JOB_STOPWORDS or len(key) < 4:
            continue
        counts[key] = counts.get(key, 0) + 1
        original.setdefault(key, token.strip("./-"))

    title_candidates = [
        token for token in title_tokens
        if token.lower().strip("./-") not in _JOB_STOPWORDS
    ]
    body_candidates = [
        original[key]
        for key, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if counts[key] >= 2
    ]
    candidates = [*ordered, *title_candidates, *body_candidates]

    result: list[str] = []
    seen: set[str] = set()
    for term in candidates:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            result.append(term)
    if ordered:
        return result[: len(ordered)]
    return result[:20]


def _term_present(text: str, term: str) -> bool:
    normalized_text = re.sub(r"[^a-z0-9+#.]+", " ", text.lower())
    normalized_term = re.sub(r"[^a-z0-9+#.]+", " ", term.lower()).strip()
    if not normalized_term:
        return False
    term_pattern = re.escape(normalized_term)
    if normalized_term == "rest":
        term_pattern = r"rest(?:ful)?"
    return bool(
        re.search(
            rf"(?<![a-z0-9+#.]){term_pattern}(?![a-z0-9+#.])",
            normalized_text,
        )
    )


def _strip_unverified_inferred_additions(
    content: str,
    rewrites: Iterable[dict[str, Any]],
    decisions: dict[str, str],
) -> tuple[str, list[str], list[str]]:
    scorable = content
    removed: list[str] = []
    confirmed: list[str] = []
    for rewrite in rewrites:
        if _text(rewrite.get("change_type")) != "inferred_claim":
            continue
        rewrite_id = _text(rewrite.get("id"))
        if decisions.get(rewrite_id, "pending") == "accepted":
            confirmed.extend(
                phrase
                for addition in _list(rewrite.get("inferred_additions"))
                if (phrase := _text(addition))
            )
            continue
        for addition in _list(rewrite.get("inferred_additions")):
            phrase = _text(addition)
            if not phrase:
                continue
            scorable = re.sub(re.escape(phrase), " ", scorable, flags=re.IGNORECASE)
            removed.append(phrase)
    return scorable, removed, confirmed


def _visible_entries(parsed: dict[str, Any], rendered_text: str, key: str) -> list[dict[str, Any]]:
    return [
        entry for entry in _list(parsed.get(key))
        if isinstance(entry, dict) and _contains_entry(rendered_text, entry)
    ]


def _project_has_link(project: dict[str, Any], raw_content: str) -> bool:
    if _text(project.get("url")) or _text(project.get("link_label")):
        return True
    name = _text(project.get("name"))
    if not name:
        return False
    start = raw_content.lower().find(name.lower())
    if start < 0:
        return False
    heading_window = raw_content[start:start + 300].split(r"\item", 1)[0]
    return bool(_URL_RE.search(heading_window) or "\\href{" in heading_window)


def _open_source_signal(parsed: dict[str, Any], rendered_text: str) -> dict[str, Any]:
    source_lines: list[str] = []
    for key in ("experience", "projects"):
        for entry in _list(parsed.get(key)):
            if not isinstance(entry, dict) or not _contains_entry(rendered_text, entry):
                continue
            for bullet in _entry_bullets(entry):
                if _OPEN_SOURCE_RE.search(bullet):
                    source_lines.append(bullet)

    contact = _dict(parsed.get("contact"))
    urls = [_text(item) for item in _list(contact.get("urls"))]
    github_present = (
        any("github.com/" in url.lower() for url in urls)
        or "github.com/" in rendered_text.lower()
    )
    return {
        "evidence_lines": source_lines,
        "github_present": github_present,
        "star_signal": any(re.search(r"\b\d[\d,.]*\+?\s+stars?\b", line, re.I) for line in source_lines),
        "gsoc": any(re.search(r"google summer of code|\bgsoc\b", line, re.I) for line in source_lines),
    }


def _project_signal(parsed: dict[str, Any], rendered_text: str, raw_content: str) -> dict[str, Any]:
    projects = _visible_entries(parsed, rendered_text, "projects")
    points = 0.0
    linked = 0
    complex_count = 0
    metric_count = 0
    generic_count = 0
    for project in projects[:4]:
        text = _entry_text(project)
        points += 4
        if _COMPLEXITY_RE.search(text):
            points += 3
            complex_count += 1
        if _metric_tokens(text):
            points += 2
            metric_count += 1
        if _project_has_link(project, raw_content):
            points += 2
            linked += 1
        if _OUTCOME_RE.search(text):
            points += 1
        if _GENERIC_PROJECT_RE.search(text):
            points -= 2
            generic_count += 1
    return {
        "raw_points": max(0.0, points),
        "visible": len(projects),
        "linked": linked,
        "complex": complex_count,
        "with_metrics": metric_count,
        "generic": generic_count,
    }


def _production_signal(parsed: dict[str, Any], rendered_text: str) -> dict[str, Any]:
    entries = _visible_entries(parsed, rendered_text, "experience")
    points = 0.0
    metrics = 0
    production = 0
    outcomes = 0
    for entry in entries[:5]:
        text = _entry_text(entry)
        points += 4
        if _metric_tokens(text):
            points += 3
            metrics += 1
        if _PRODUCTION_RE.search(text):
            points += 3
            production += 1
        if _OUTCOME_RE.search(text):
            points += 2
            outcomes += 1
    return {
        "raw_points": points,
        "visible": len(entries),
        "with_metrics": metrics,
        "production_scope": production,
        "outcomes": outcomes,
    }


def _skills(parsed: dict[str, Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    values: list[object] = list(_list(parsed.get("skills")))
    for items in _dict(parsed.get("skills_by_category")).values():
        values.extend(_list(items))
    for value in values:
        skill = _text(value)
        if skill and skill.lower() not in seen:
            seen.add(skill.lower())
            result.append(skill)
    return result


def _category(
    definition: QualityCategoryDefinition,
    score: float,
    evidence: list[str],
    improvements: list[str],
) -> dict[str, Any]:
    return {
        "key": definition.key,
        "label": definition.label,
        "score": _bounded(score, definition.maximum),
        "max": definition.maximum,
        "evidence": evidence or ["No supported evidence was found in the rendered artifact."],
        "improvements": improvements[:3],
    }


def _technical_categories(
    profile: QualityProfile,
    parsed: dict[str, Any],
    rendered_text: str,
    raw_content: str,
    job_terms: list[str],
) -> list[dict[str, Any]]:
    project = _project_signal(parsed, rendered_text, raw_content)
    production = _production_signal(parsed, rendered_text)
    open_source = _open_source_signal(parsed, rendered_text)
    skills = _skills(parsed)
    surfaced_skills = [skill for skill in skills if _term_present(rendered_text, skill)]
    skill_job_terms = [
        term
        for term in job_terms
        if any(_term_present(skill, term) or _term_present(term, skill) for skill in skills)
    ]
    relevant_skills = [
        term for term in skill_job_terms if _term_present(rendered_text, term)
    ]

    results: list[dict[str, Any]] = []
    for definition in profile.categories:
        if definition.key == "open_source":
            lines = open_source["evidence_lines"]
            raw_score = len(lines) * 7
            raw_score += 7 if open_source["star_signal"] else 0
            raw_score += 5 if open_source["gsoc"] else 0
            if not lines and open_source["github_present"]:
                raw_score = min(10, 3 + project["linked"] * 2)
            score = raw_score * definition.maximum / 35
            evidence = []
            if lines:
                evidence.append(f"{len(lines)} explicit third-party/open-source contribution signal(s) are visible.")
            elif open_source["github_present"]:
                evidence.append(
                    "A GitHub profile and visible personal repositories receive bounded "
                    "portfolio credit; they are not treated as third-party contributions."
                )
            improvements = [] if lines else [
                "If applicable, add verifiable third-party contributions, merged pull requests, or community impact; do not relabel personal projects as open source."
            ]
            results.append(_category(definition, score, evidence, improvements))
        elif definition.key == "projects":
            score = min(30.0, project["raw_points"]) * definition.maximum / 30
            evidence = [
                f"{project['visible']} project(s) are visible; {project['linked']} include a repository or demo reference.",
                f"{project['complex']} show advanced architecture and {project['with_metrics']} show measurable scope.",
            ]
            improvements: list[str] = []
            if project["visible"] == 0:
                improvements.append("Surface the strongest role-relevant project with concrete implementation evidence.")
            if project["linked"] < project["visible"]:
                improvements.append("Add a verified repository or live-demo link to projects that currently lack evidence.")
            if project["with_metrics"] == 0 and project["visible"]:
                improvements.append("Add truthful scale, usage, test, latency, or delivery evidence to the strongest project.")
            results.append(_category(definition, score, evidence, improvements))
        elif definition.key == "production":
            score = min(25.0, production["raw_points"]) * definition.maximum / 25
            evidence = [
                f"{production['visible']} work experience entrie(s) are visible; {production['production_scope']} show production scope.",
                f"{production['with_metrics']} include measurable scope and {production['outcomes']} describe outcomes.",
            ]
            improvements = []
            if production["visible"] == 0:
                improvements.append("Surface supported internship, employment, volunteer, or production delivery evidence.")
            if production["with_metrics"] == 0 and production["visible"]:
                improvements.append("Quantify a supported production outcome, scale, reliability change, or delivery scope.")
            results.append(_category(definition, score, evidence, improvements))
        elif definition.key == "technical_skills":
            breadth_score = min(4.0, len(surfaced_skills) / 4)
            relevance_score = 6.0 * len(relevant_skills) / max(1, len(skill_job_terms))
            raw_score = breadth_score + relevance_score
            score = raw_score * definition.maximum / 10
            evidence = [
                f"{len(surfaced_skills)} supported skills are surfaced and {len(relevant_skills)}/{len(skill_job_terms)} relevant capability terms are present."
            ]
            improvements = [] if relevant_skills else [
                "Surface only job-relevant technical capabilities already supported by experience or projects."
            ]
            results.append(_category(definition, score, evidence, improvements))
    return results


def _general_categories(
    profile: QualityProfile,
    parsed: dict[str, Any],
    rendered_text: str,
    raw_content: str,
    job_terms: list[str],
) -> list[dict[str, Any]]:
    production = _production_signal(parsed, rendered_text)
    projects = _project_signal(parsed, rendered_text, raw_content)
    skills = [skill for skill in _skills(parsed) if _term_present(rendered_text, skill)]
    matching_terms = [term for term in job_terms if _term_present(rendered_text, term)]
    supported = _supported_source_text(parsed)
    outcome_lines = [
        line for line in supported.splitlines()
        if _OUTCOME_RE.search(line) and _metric_tokens(line) and _term_present(rendered_text, line[:40])
    ]
    urls = _URL_RE.findall(raw_content)

    results: list[dict[str, Any]] = []
    for definition in profile.categories:
        if definition.key == "outcomes":
            score = min(definition.maximum, len(outcome_lines) * 8 + production["outcomes"] * 3)
            evidence = [f"{len(outcome_lines)} visible evidence line(s) combine outcomes with measurable scope."]
            improvements = [] if outcome_lines else [
                "Add a truthful result, scale, time saving, quality change, or stakeholder outcome to the strongest experience bullet."
            ]
        elif definition.key == "role_experience":
            relevance = len(matching_terms) / max(1, len(job_terms))
            score = min(definition.maximum, production["visible"] * 6 + relevance * 20)
            evidence = [
                f"{production['visible']} experience entrie(s) are visible and {len(matching_terms)}/{len(job_terms)} evaluated job terms are surfaced."
            ]
            improvements = [] if matching_terms else [
                "Reframe existing experience using supported terminology from the target role."
            ]
        elif definition.key == "capabilities":
            score = min(definition.maximum, len(skills) * 1.5 + projects["complex"] * 3)
            evidence = [f"{len(skills)} supported capabilities are visible in the final artifact."]
            improvements = [] if skills else [
                "Surface the professional capabilities already demonstrated by the candidate's work."
            ]
        else:
            evidence_count = len(urls) + production["with_metrics"] + projects["linked"]
            score = min(definition.maximum, evidence_count * 2)
            evidence = [
                f"The artifact contains {len(urls)} link(s), {production['with_metrics']} measured work entrie(s), and {projects['linked']} linked project(s)."
            ]
            improvements = [] if evidence_count else [
                "Add verifiable links, credentials, or measurable evidence where the source resume supports them."
            ]
        results.append(_category(definition, score, evidence, improvements))
    return results


def _axis(score: float, evidence: list[str], improvements: list[str]) -> dict[str, Any]:
    return {
        "score": _bounded(score, 100),
        "max": 100,
        "evidence": evidence,
        "improvements": improvements[:3],
    }


def _job_fit_axis(
    rendered_text: str,
    supported_text: str,
    job_terms: list[str],
) -> dict[str, Any]:
    if not job_terms:
        return _axis(
            0,
            ["The job description did not expose enough stable terms for deterministic matching."],
            ["Review the artifact manually against the complete job description."],
        )
    matched = [
        term
        for term in job_terms
        if _term_present(rendered_text, term) and _term_present(supported_text, term)
    ]
    supported_missing = [
        term
        for term in job_terms
        if term not in matched and _term_present(supported_text, term)
    ]
    unsupported = [
        term
        for term in job_terms
        if term not in matched and term not in supported_missing
    ]
    score = 100 * len(matched) / len(job_terms)
    evidence = [f"Surfaced {len(matched)}/{len(job_terms)} evaluated job terms."]
    if matched:
        evidence.append("Matched: " + ", ".join(matched[:8]))
    improvements: list[str] = []
    if supported_missing:
        improvements.append(
            "Surface existing supported evidence for: " + ", ".join(supported_missing[:6])
        )
    if unsupported:
        improvements.append(
            "Unverified job gaps (do not add without evidence): " + ", ".join(unsupported[:6])
        )
    return _axis(score, evidence, improvements)


def _parseability_axis(content: str, rendered_text: str, parsed: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "contact": bool(_EMAIL_RE.search(rendered_text) or _PHONE_RE.search(rendered_text)),
        "experience": bool(re.search(r"\\subsection\*\{.*experience", content, re.I) or _visible_entries(parsed, rendered_text, "experience")),
        "education": bool(re.search(r"\\subsection\*\{.*education", content, re.I) or "education" in rendered_text.lower()),
        "skills": bool(re.search(r"\\subsection\*\{.*skills", content, re.I) or "skills" in rendered_text.lower()),
        "links": bool(_URL_RE.search(content) or "\\href{" in content or "\\url{" in content),
        "measurable evidence": bool(_metric_tokens(rendered_text)),
    }
    weights = {
        "contact": 20,
        "experience": 25,
        "education": 15,
        "skills": 20,
        "links": 10,
        "measurable evidence": 10,
    }
    score = sum(weights[key] for key, passed in checks.items() if passed)
    passed = [key for key, value in checks.items() if value]
    failed = [key for key, value in checks.items() if not value]
    evidence = ["Recognized: " + ", ".join(passed)] if passed else ["No standard resume signals were recognized."]
    improvements = ["Restore recognizable " + ", ".join(failed) + "."] if failed else []
    return _axis(score, evidence, improvements)


def _readiness(score: float) -> str:
    if score >= 85:
        return "strong"
    if score >= 70:
        return "competitive"
    if score >= 50:
        return "developing"
    return "needs_work"


def validate_quality_evaluation(evaluation: dict[str, Any]) -> None:
    """Raise ``ValueError`` if a generated evaluation violates score bounds."""
    if evaluation.get("status") != "ready":
        return
    overall = evaluation.get("overall_score")
    if not isinstance(overall, (int, float)) or not 0 <= overall <= 100:
        raise ValueError("Resume quality overall score must be between 0 and 100.")
    axes = evaluation.get("axes")
    if not isinstance(axes, dict) or set(axes) != {"job_fit", "evidence_quality", "parseability"}:
        raise ValueError("Resume quality evaluation is missing required axes.")
    for value in axes.values():
        if not isinstance(value, dict) or not 0 <= float(value.get("score", -1)) <= float(value.get("max", 0)):
            raise ValueError("Resume quality axis score is outside its declared bounds.")
    for category in evaluation.get("categories") or []:
        if not 0 <= float(category.get("score", -1)) <= float(category.get("max", 0)):
            raise ValueError("Resume quality category score is outside its declared bounds.")


def evaluate_resume_quality(
    *,
    parsed: dict[str, Any],
    content: str,
    job: object,
    rewrites: Iterable[dict[str, Any]] = (),
    rewrite_decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate a rendered artifact using supported, user-scoped evidence."""
    profile = select_quality_profile(parsed, job)
    decisions = rewrite_decisions or {}
    scorable_content, unverified_additions, confirmed_additions = (
        _strip_unverified_inferred_additions(
        content,
        rewrites,
        decisions,
        )
    )
    rendered_text = _latex_plain_text(scorable_content)
    supported_text = "\n".join(
        [_supported_source_text(parsed), *confirmed_additions]
    )
    terms = _job_terms(job)
    categories = (
        _technical_categories(profile, parsed, rendered_text, scorable_content, terms)
        if profile is not GENERAL_PROFESSIONAL
        else _general_categories(profile, parsed, rendered_text, scorable_content, terms)
    )

    evidence_score = 100 * sum(float(item["score"]) for item in categories) / sum(
        float(item["max"]) for item in categories
    )
    axes = {
        "job_fit": _job_fit_axis(rendered_text, supported_text, terms),
        "evidence_quality": _axis(
            evidence_score,
            [f"The {profile.label} rubric scored {sum(float(item['score']) for item in categories):.1f}/100 category points."],
            [improvement for item in categories for improvement in item["improvements"]][:3],
        ),
        "parseability": _parseability_axis(scorable_content, rendered_text, parsed),
    }
    overall = round(
        axes["job_fit"]["score"] * 0.45
        + axes["evidence_quality"]["score"] * 0.45
        + axes["parseability"]["score"] * 0.10,
        1,
    )

    strengths = [
        item["label"]
        for item in sorted(
            categories,
            key=lambda item: float(item["score"]) / max(1.0, float(item["max"])),
            reverse=True,
        )
        if float(item["score"]) / max(1.0, float(item["max"])) >= 0.65
    ][:3]
    improvements = [
        improvement
        for item in sorted(
            categories,
            key=lambda item: float(item["score"]) / max(1.0, float(item["max"])),
        )
        for improvement in item["improvements"]
    ][:4]
    improvements.extend(axes["job_fit"]["improvements"][:1])

    evaluation = {
        "schema_version": 1,
        "rubric_version": RUBRIC_VERSION,
        "profile": profile.key,
        "profile_label": profile.label,
        "status": "ready",
        "evaluation_mode": EVALUATION_MODE,
        "source_attribution": dict(SOURCE_ATTRIBUTION),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": overall,
        "readiness": _readiness(overall),
        "axes": axes,
        "categories": categories,
        "strengths": strengths,
        "improvements": list(dict.fromkeys(improvements))[:5],
        "truthfulness": {
            "unverified_inferred_additions_excluded": len(unverified_additions),
            "excluded_phrases": unverified_additions[:10],
        },
        "disclaimer": DISCLAIMER,
    }
    validate_quality_evaluation(evaluation)
    return evaluation


def unavailable_quality_evaluation(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "rubric_version": RUBRIC_VERSION,
        "status": "unavailable",
        "evaluation_mode": EVALUATION_MODE,
        "source_attribution": dict(SOURCE_ATTRIBUTION),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "disclaimer": DISCLAIMER,
    }


def quality_planner_guidance(evaluation: dict[str, Any]) -> str:
    """Build bounded plan guidance from an already validated evaluation."""
    if evaluation.get("status") != "ready":
        return ""
    profile = _text(evaluation.get("profile_label"))
    priorities = [_text(item) for item in _list(evaluation.get("improvements")) if _text(item)]
    category_scores = [
        {
            "category": _text(item.get("label")),
            "score": item.get("score"),
            "max": item.get("max"),
        }
        for item in _list(evaluation.get("categories"))
        if isinstance(item, dict)
    ]
    payload = {
        "profile": profile,
        "category_scores": category_scores,
        "strengths_to_preserve": _list(evaluation.get("strengths"))[:3],
        "priorities": priorities[:4],
        "rules": [
            "Select only evidence present in the source resume.",
            "Prefer measurable impact, production scope, and verifiable links.",
            "Never invent metrics, tools, credentials, employers, or contribution claims.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True)
