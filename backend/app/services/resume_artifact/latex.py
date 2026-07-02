"""LaTeX rendering and PDF generation for resume artifacts."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


from app.models.job import Job
from app.models.profile import Profile
from app.models.tailored_resume import TailoredResume
from app.models.user import User
from app.services.resume_artifact.parsed import _derive_project_url, _extract_resume_data, _find_contact_url, _is_valid_project_name
from app.services.resume_artifact.plan import _default_artifact_plan, _emphasis_terms, _layout_profile, _preferred_bullet_indices, _preferred_section_limits, _preferred_skills_focus, _rank_projects
from app.services.resume_artifact.rewrites import _apply_bullet_rewrites, _filter_rewrites_by_decisions, _index_rewrites
from app.services.resume_artifact.textnorm import _clean, _extract_phone, _merge_unique, _quantifiable_measure_spans, _split_description_bullets, _split_project_bullets

logger = logging.getLogger(__name__)


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
    """Sanitize a URL for use inside a LaTeX ``\\url{}``/``\\href{}`` argument.

    Strips characters that are invalid in a real URL but carry LaTeX meaning and
    could break out of the argument or form a control sequence — backslashes
    (control sequences), braces (argument delimiters), and whitespace/control
    chars. URL-legal characters (including ``%`` and ``#``, which hyperref
    handles) are left intact so legitimate links still render. Defense-in-depth:
    the profile URL fields are also validated at the API boundary, but
    resume-parsed contact/project links bypass that path, so this is the
    catch-all. See the security-audit note on ``_latex_url``.
    """
    cleaned = _clean(value).replace("\\", "").replace("{", "").replace("}", "")
    return "".join(ch for ch in cleaned if ch.isprintable() and not ch.isspace())


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
            # Explicitly disable \write18 shell escape (blocks RCE) and confine
            # \input/\openin/\openout to the temp working dir via paranoid file
            # access, so a LaTeX-injection payload can't read absolute paths
            # (e.g. /app/.env) or traverse out with `..`. Defense-in-depth.
            "-no-shell-escape",
            "-output-directory",
            str(tmp_path),
            str(tex_path),
        ]
        # openin_any/openout_any=p (paranoid) are honored by web2c via env vars;
        # they only block absolute/`..` user file access, not kpathsea package
        # loads, so standard resume packages still compile.
        env = {**os.environ, "openin_any": "p", "openout_any": "p"}
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(tmp_path),
            env=env,
        )
        if result.returncode != 0 or not pdf_path.exists():
            raise ValueError(
                "Failed to compile LaTeX resume artifact to PDF."
                f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

        return pdf_path.read_bytes()


_PDF_RENDER_SEMAPHORE = asyncio.Semaphore(2)


async def render_resume_artifact_pdf_async(content: str) -> bytes:
    """Async wrapper around ``render_resume_artifact_pdf`` (audit H1).

    Offloads the blocking pdflatex subprocess to a worker thread so it never
    freezes the event loop, and caps concurrent compilations.
    """
    async with _PDF_RENDER_SEMAPHORE:
        return await asyncio.to_thread(render_resume_artifact_pdf, content)


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
