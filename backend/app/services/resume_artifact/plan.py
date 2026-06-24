"""Artifact plan, layout profile, and relevance scoring."""

from __future__ import annotations

import json
import logging
import re
from typing import Any


from app.models.job import Job
from app.models.tailored_resume import TailoredResume
from app.clients.llm_client import generate_message
from app.services.resume_tailor import (
    extract_jd_must_surface,
)
from app.services.resume_artifact.textnorm import _clean, _latex_plain_text, _merge_unique, _metric_tokens, _resume_body_contains_term, _split_description_bullets, _split_project_bullets

logger = logging.getLogger(__name__)


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


def _build_artifact_plan_prompt(
    parsed: dict[str, Any],
    job: Job,
    tailored: TailoredResume,
    quality_guidance: str = "",
) -> str:
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
    if quality_guidance:
        parts.extend([
            "",
            "SUPPORTED-EVIDENCE QUALITY GATE:",
            quality_guidance,
        ])
    return "\n".join(parts)


async def _build_resume_artifact_plan(
    *,
    parsed: dict[str, Any],
    job: Job,
    tailored: TailoredResume,
    quality_guidance: str = "",
) -> dict[str, Any]:
    fallback = _expand_plan_to_fill_page(parsed, job, _default_artifact_plan(parsed, job, tailored))
    if not job.description:
        return fallback

    try:
        result = await generate_message(
            system_prompt=ARTIFACT_PLAN_SYSTEM_PROMPT,
            user_prompt=_build_artifact_plan_prompt(
                parsed,
                job,
                tailored,
                quality_guidance,
            ),
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


def score_resume_content_against_job(content: str, job: Job) -> float | None:
    """Deterministically score rendered resume content against a job description."""
    if not content or not (job.description or ""):
        return None
    jd = extract_jd_must_surface(job.description or "")
    terms = jd.get("must_surface") or []
    if not terms:
        return None

    body_content = re.split(
        r"\\subsection\*\{Technical Skills\}",
        content,
        maxsplit=1,
    )[0]
    body = _latex_plain_text(body_content).lower()
    hits = sum(1 for term in terms if _resume_body_contains_term(body, str(term)))
    return round(100.0 * hits / len(terms), 1)
