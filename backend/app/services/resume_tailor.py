"""AI-powered resume tailoring service.

Given a user's parsed resume and a target job, generates specific,
actionable suggestions for tailoring the resume to maximize match.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.clients.llm_client import generate_message

if TYPE_CHECKING:
    from app.models.profile import Profile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert resume coach and ATS optimization specialist.
Your job is to analyze a candidate's resume against a specific job posting
and provide concrete, actionable tailoring suggestions.

You must return ONLY valid JSON with this exact structure:
{
  "summary": "2-3 sentence overview of the tailoring strategy",
  "skills_to_emphasize": ["skill1", "skill2"],
  "skills_to_add": ["skill3", "skill4"],
  "keywords_to_add": ["keyword1", "keyword2"],
  "bullet_rewrites": [
    {
      "section": "experience|projects",
      "original": "original bullet text",
      "rewritten": "improved bullet text",
      "reason": "why this change helps",
      "experience_index": 0,
      "project_index": null,
      "change_type": "keyword|reframe|inferred_claim",
      "inferred_additions": ["phrase added beyond the original bullet"],
      "requires_user_confirm": true
    }
  ],
  "section_suggestions": [
    {
      "section": "summary|experience|skills|projects|education",
      "suggestion": "what to change and why"
    }
  ],
  "overall_strategy": "paragraph explaining the overall approach"
}

Rules:
- skills_to_emphasize: skills the candidate already has that should be more prominent
- skills_to_add: skills from the JD that the candidate likely has but didn't list
- keywords_to_add: ATS-relevant terms from the JD missing from the resume
- bullet_rewrites: AGGRESSIVE DEFAULT MODE. Rewrite 12-16 bullets total, evenly distributed across the resume. COVERAGE FLOOR (hard requirement):
  * Every experience at indices 0, 1, 2 MUST receive at least 2 rewrites.
  * Every project at indices 0, 1, 2 (when they exist) MUST receive at least 2 rewrites.
  * No single section may hold more than half of the total rewrites.
  * Across the full set, at least 5 rewrites MUST be change_type="inferred_claim" AND those inferred_claims MUST be spread across BOTH experience and project sections (not bunched on one entry).
  * Across the full set, at least 3 rewrites MUST be change_type="keyword".
  * MUST_SURFACE_BASELINE: If MUST_SURFACE_IN_BULLET_TEXT terms are provided (below), at least 75% of them (rounded up) MUST appear verbatim in the final bullet_rewrites[].rewritten strings. Fail-safe: Never drop a high-priority term (JavaScript, Java, unit testing) once surfaced in favor of other changes.
  For experience bullets, set section="experience" and provide experience_index. For project bullets, set section="projects" and provide project_index. Use quantified achievements where possible.
- For every rewrite, classify change_type precisely:
  - "keyword" = you only swapped in JD-aligned terminology; the underlying scope and claims are unchanged.
  - "reframe" = same facts, sharper angle (e.g. calling a mobile feature "customer-facing product work"); no new capability asserted.
  - "inferred_claim" = the rewrite asserts a capability, tool, scope, or outcome NOT explicit in the original bullet but plausibly true for the role (e.g. adding "component-based web UI" to an iOS role that likely had an internal web companion, or "accessible, WCAG-compliant" to a UI that plausibly considered accessibility).
- For inferred_claim rewrites, list every inferred phrase in inferred_additions and set requires_user_confirm=true. For keyword/reframe set requires_user_confirm=false and inferred_additions=[].
- Be aggressive with inferred_claim rewrites when they strengthen the match: surface plausible truthful-adjacent claims and let the user accept or reject. Never fabricate specific metrics or named tools the candidate did not list somewhere in their resume, but you MAY surface likely-true capabilities, practices, and scope language that match the JD.
- Ensure every experience and every top project has at least TWO proposed rewrites — no entry may receive zero or one rewrite while another entry receives three or more. Balance coverage first; depth second.
- section_suggestions: high-level guidance for each resume section
- Be specific and actionable, not generic
- Do NOT fabricate experience or skills the candidate doesn't have
- Focus on reframing existing experience to match job language
- Keep the candidate's authentic voice
- Preserve every concrete metric, count, percentage, scale marker, and scope indicator that already appears in the source bullet.
- Prefer rewrites that improve ATS keyword alignment without making the bullet less measurable.
- Prioritize JD phrases that are likely to affect ATS and recruiter screening, such as frameworks, testing tools, frontend/backend architecture terms, accessibility, CI/CD, telemetry, experimentation, personalization, collaboration, and performance.
- When the job is frontend-heavy but the candidate's strongest evidence is in projects, still produce experience rewrites that truthfully surface transferable software engineering practices instead of inventing frontend ownership.
- Rewrite project bullets aggressively when projects are the strongest proof of fit for the role.
- For frontend/fullstack web roles, prefer the concise recruiter-ready style used in strong manual tailoring:
  - customer-facing product features
  - scalable, maintainable application behavior
  - RESTful APIs and client-server integration
  - telemetry, testing, debugging, and Git-based collaboration
  - responsive, component-based UI language for the strongest web projects
  - preserve a crisp 1-sentence bullet style unless a second clause is needed to preserve measurable impact
- When the JD mentions personalization, experimentation, A/B testing, accessibility, WCAG, internationalization, or experimentation platforms, surface those exact phrases in `keywords_to_add` and weave them into 1-2 bullet rewrites where the candidate has a truthful basis (e.g. a feature flag, an experiment, a reusable component, an accessibility concern).
- Rewrite at least one experience bullet AND one project bullet for any frontend/fullstack JD, even when the score is high; the goal is ATS keyword density without inventing capabilities.
- Provide rewrites for the candidate's TOP 3 experiences and TOP 3 projects (by relevance) so the planner has tailored options for every visible bullet on a 3/3/3 + 3/2/2 page.
- Do NOT suggest section_suggestions that recommend removing concrete content (locations, dates, certificates, project links, metrics). Only recommend reframing or reordering.
"""


def _build_resume_context(profile: Profile) -> str:
    """Build resume context string from parsed resume data."""
    parsed = profile.resume_parsed or {}
    parts: list[str] = []

    # Skills
    skills = parsed.get("skills", [])
    if skills:
        parts.append(f"SKILLS: {', '.join(skills)}")

    # Experience
    experience = parsed.get("experience", [])
    if experience:
        parts.append("\nEXPERIENCE:")
        for i, exp in enumerate(experience):
            company = exp.get("company", "Unknown")
            title = exp.get("title", "Unknown")
            start = exp.get("start_date", "")
            end = exp.get("end_date", "Present") or "Present"
            bullets = exp.get("bullets", [])
            desc = exp.get("description", "")
            parts.append(f"  [{i}] {title} at {company} ({start} - {end})")
            if bullets:
                for bullet in bullets[:4]:
                    parts.append(f"      - {bullet}")
            elif desc:
                parts.append(f"      {desc}")

    # Education
    education = parsed.get("education", [])
    if education:
        parts.append("\nEDUCATION:")
        for edu in education:
            inst = edu.get("institution", "Unknown")
            degree = edu.get("degree", "")
            field = edu.get("field", "")
            grad = edu.get("graduation_date", "")
            parts.append(f"  {degree} in {field} from {inst} ({grad})")

    # Projects
    projects = parsed.get("projects", [])
    if projects:
        parts.append("\nPROJECTS:")
        for proj in projects:
            name = proj.get("name", "Unknown")
            bullets = proj.get("bullets", [])
            desc = proj.get("description", "")
            techs = proj.get("technologies", [])
            parts.append(f"  {name}:")
            if bullets:
                for bullet in bullets[:3]:
                    parts.append(f"    - {bullet}")
            elif desc:
                parts.append(f"    {desc}")
            if techs:
                parts.append(f"    Technologies: {', '.join(techs)}")

    certificates = parsed.get("certificates", [])
    if certificates:
        parts.append("\nCERTIFICATES:")
        for certificate in certificates[:4]:
            parts.append(f"  - {certificate}")

    # Target roles/locations from profile
    if profile.target_roles:
        parts.append(f"\nTARGET ROLES: {', '.join(profile.target_roles)}")
    if profile.target_locations:
        parts.append(f"TARGET LOCATIONS: {', '.join(profile.target_locations)}")

    return "\n".join(parts) if parts else "(no resume data)"


_ROLE_FAMILY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fullstack", ("full-stack", "fullstack", "full stack")),
    ("frontend", ("front-end", "frontend", "front end")),
    ("backend", ("back-end", "backend", "back end")),
    ("mobile", ("ios", "android", "react native", "mobile")),
    ("data", ("data engineer", "ml engineer", "machine learning engineer")),
)

_TECH_HINTS: tuple[str, ...] = (
    "React", "Next.js", "Node.js", "TypeScript", "JavaScript", "Python", "Java",
    "Go", "C#", "Ruby on Rails", "GraphQL", "REST", "RESTful", "gRPC",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka",
    "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform",
    "Redux", "Vue", "Angular", "Svelte",
    "Swift", "Kotlin", "Flutter",
    "Playwright", "Cypress", "Jest", "Vitest",
    "TensorFlow", "PyTorch", "Scikit-learn",
)

_METHOD_HINTS: tuple[str, ...] = (
    "SDLC", "TDD", "Agile", "SCRUM", "Extreme Programming", "XP",
    "unit testing", "integration testing", "peer reviews", "code reviews",
    "CI/CD", "pair programming", "A/B testing", "experimentation",
    "accessibility", "WCAG", "internationalization",
    "customer empathy", "customer-facing", "cross-functional",
    "web applications",
)


def extract_jd_must_surface(job_description: str) -> dict:
    """Parse a job description and return the terms that should be surfaced
    verbatim in the tailored resume's experience/project bullets (not just in
    the skills section).

    Returns a dict with role_family, tech_terms, methodology_terms, and a
    flat ``must_surface`` list ranked by priority.
    """
    desc = (job_description or "")
    low = desc.lower()

    role_family: str | None = None
    for family, patterns in _ROLE_FAMILY_HINTS:
        if any(p in low for p in patterns):
            role_family = family
            break

    tech_hits = [
        term for term in _TECH_HINTS
        if term.lower() in low or term.lower().replace(".", "") in low.replace(".", "")
    ]
    method_hits: list[str] = []
    for term in _METHOD_HINTS:
        if term.lower() in low:
            method_hits.append(term)

    # Priority: role family -> technology -> methodology.
    must_surface: list[str] = []
    if role_family:
        must_surface.append({
            "fullstack": "full-stack",
            "frontend": "frontend",
            "backend": "backend",
            "mobile": "mobile",
            "data": "data",
        }[role_family])
    must_surface.extend(tech_hits)
    must_surface.extend(method_hits)

    # Dedup preserve order.
    seen: set[str] = set()
    ordered: list[str] = []
    for term in must_surface:
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(term)

    return {
        "role_family": role_family,
        "tech_terms": tech_hits,
        "methodology_terms": method_hits,
        "must_surface": ordered,
    }


def _build_job_context(job_data: dict) -> str:
    """Build job context string."""
    parts: list[str] = []

    title = job_data.get("title", "Unknown")
    company = job_data.get("company_name", "Unknown")
    parts.append(f"POSITION: {title} at {company}")

    location = job_data.get("location")
    if location:
        parts.append(f"LOCATION: {location}")
    if job_data.get("remote"):
        parts.append("REMOTE: Yes")

    level = job_data.get("experience_level")
    if level:
        parts.append(f"LEVEL: {level}")

    desc = job_data.get("description", "")
    if desc:
        # Truncate very long descriptions to stay within token limits
        if len(desc) > 6000:
            desc = desc[:6000] + "\n[...truncated]"
        parts.append(f"\nJOB DESCRIPTION:\n{desc}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Bullet rewrite normalization
# ---------------------------------------------------------------------------


_VALID_CHANGE_TYPES = {"keyword", "reframe", "inferred_claim"}


def _coverage_deficits(
    rewrites: list,
    profile: Profile,
    must_surface: list[str] | None = None,
) -> list[str]:
    """Return human-readable deficit messages when aggressive-mode coverage
    floors are violated. Empty list means coverage is satisfied.

    Floors: every exp/project index 0..2 gets >=2 rewrites; >=5 inferred_claim
    spread across BOTH sections; >=3 keyword total. When ``must_surface`` is
    provided, each term MUST appear verbatim (case-insensitive substring) in
    at least one rewritten bullet. High-priority terms (JavaScript, Java, unit
    testing, integration testing) get stricter enforcement.
    """
    parsed = getattr(profile, "resume_parsed", None) or {}
    exp_count = min(len(parsed.get("experience") or []), 3)
    proj_count = min(len(parsed.get("projects") or []), 3)

    exp_hits: dict[int, int] = {}
    proj_hits: dict[int, int] = {}
    inferred_in_exp = 0
    inferred_in_proj = 0
    keyword_count = 0
    combined_bullet_text = ""
    for r in rewrites or []:
        if not isinstance(r, dict):
            continue
        section = (r.get("section") or "").lower()
        change = (r.get("change_type") or "").lower()
        combined_bullet_text += " " + (r.get("rewritten") or "")
        if change == "keyword":
            keyword_count += 1
        if section == "experience":
            idx = r.get("experience_index")
            if isinstance(idx, int) and 0 <= idx < exp_count:
                exp_hits[idx] = exp_hits.get(idx, 0) + 1
                if change == "inferred_claim":
                    inferred_in_exp += 1
        elif section == "projects":
            idx = r.get("project_index")
            if isinstance(idx, int) and 0 <= idx < proj_count:
                proj_hits[idx] = proj_hits.get(idx, 0) + 1
                if change == "inferred_claim":
                    inferred_in_proj += 1

    deficits: list[str] = []
    for i in range(exp_count):
        if exp_hits.get(i, 0) < 2:
            deficits.append(f'experience_index={i} needs >=2 rewrites (got {exp_hits.get(i, 0)})')
    for i in range(proj_count):
        if proj_hits.get(i, 0) < 2:
            deficits.append(f'project_index={i} needs >=2 rewrites (got {proj_hits.get(i, 0)})')
    total_inferred = inferred_in_exp + inferred_in_proj
    if total_inferred < 5:
        deficits.append(f'need >=5 total inferred_claim rewrites (got {total_inferred})')
    if inferred_in_exp < 2 and exp_count:
        deficits.append(f'need >=2 inferred_claim rewrites in experience section (got {inferred_in_exp})')
    if inferred_in_proj < 2 and proj_count:
        deficits.append(f'need >=2 inferred_claim rewrites in projects section (got {inferred_in_proj})')
    if keyword_count < 3:
        deficits.append(f'need >=3 keyword rewrites total (got {keyword_count})')

    if must_surface:
        low_text = combined_bullet_text.lower()
        missing = [t for t in must_surface if t.lower() not in low_text]
        if missing:
            high_priority = {"javascript", "java", "unit testing", "integration testing"}
            high_missing = [t for t in missing if t.lower() in high_priority]
            if high_missing:
                deficits.append(
                    f"HIGH PRIORITY must_surface missing: {', '.join(high_missing)} — "
                    f"these are mainstream tech/practices that MUST appear in a bullet"
                )
            else:
                deficits.append(
                    "must_surface terms missing from any bullet_rewrites[].rewritten: "
                    + ", ".join(missing)
                )
    return deficits


def _infer_change_type(original: str, rewritten: str) -> tuple[str, list[str]]:
    """Fallback classifier when the LLM omits change_type.

    Finds content words in the rewrite that do not appear in the original; if
    any, classify as inferred_claim.
    """
    import re as _re

    def _words(text: str) -> set[str]:
        return {
            w.lower()
            for w in _re.findall(r"[A-Za-z][A-Za-z0-9+.#/-]{2,}", text or "")
            if w.lower() not in {
                "the", "and", "for", "with", "that", "this", "from", "into",
                "using", "used", "our", "your", "their",
            }
        }

    original_words = _words(original)
    rewritten_words = _words(rewritten)
    new_words = sorted(rewritten_words - original_words)
    if len(new_words) >= 3:
        return "inferred_claim", new_words[:8]
    if new_words:
        return "keyword", []
    return "reframe", []


def _normalize_bullet_rewrites(rewrites: list) -> list[dict]:
    normalized: list[dict] = []
    for idx, rewrite in enumerate(rewrites or []):
        if not isinstance(rewrite, dict):
            continue
        original = (rewrite.get("original") or "").strip()
        rewritten = (rewrite.get("rewritten") or "").strip()
        if not original or not rewritten:
            continue

        change_type = (rewrite.get("change_type") or "").strip().lower()
        inferred_additions = rewrite.get("inferred_additions") or []
        if change_type not in _VALID_CHANGE_TYPES:
            change_type, auto_additions = _infer_change_type(original, rewritten)
            if not inferred_additions and auto_additions:
                inferred_additions = auto_additions
        if change_type != "inferred_claim":
            inferred_additions = []

        requires_confirm = rewrite.get("requires_user_confirm")
        if not isinstance(requires_confirm, bool):
            requires_confirm = change_type == "inferred_claim"

        normalized.append({
            "id": rewrite.get("id") or f"rw-{idx}",
            "section": rewrite.get("section") or "experience",
            "original": original,
            "rewritten": rewritten,
            "reason": rewrite.get("reason") or "",
            "experience_index": rewrite.get("experience_index"),
            "project_index": rewrite.get("project_index"),
            "change_type": change_type,
            "inferred_additions": [
                str(item).strip() for item in inferred_additions if str(item).strip()
            ],
            "requires_user_confirm": requires_confirm,
        })
    return normalized


# ---------------------------------------------------------------------------
# Main tailoring function
# ---------------------------------------------------------------------------


async def tailor_resume(
    job_data: dict,
    profile: Profile,
    score: float | None = None,
    breakdown: dict | None = None,
) -> dict:
    """Generate resume tailoring suggestions for a specific job.

    Args:
        job_data: Job fields dict (title, company_name, description, etc.)
        profile: User profile with resume_parsed
        score: Optional match score for context
        breakdown: Optional score breakdown for context

    Returns:
        Dict with tailoring suggestions + model metadata.

    Raises:
        ValueError: If no LLM provider is configured.
    """
    resume_ctx = _build_resume_context(profile)
    job_ctx = _build_job_context(job_data)

    jd_terms = extract_jd_must_surface(job_data.get("description") or "")
    must_surface = jd_terms.get("must_surface") or []
    role_family = jd_terms.get("role_family")

    # Build user prompt with optional score context
    user_parts = [
        "Analyze this resume against the job posting and provide tailoring suggestions.",
        "Optimize for truthful ATS alignment and recruiter scan quality.",
        "",
        "--- CANDIDATE RESUME ---",
        resume_ctx,
        "",
        "--- TARGET JOB ---",
        job_ctx,
    ]

    if must_surface:
        high_priority = {"javascript", "java", "unit testing", "integration testing"}
        high_must = [t for t in must_surface if t.lower() in high_priority]
        user_parts.extend([
            "",
            "--- MUST_SURFACE_IN_BULLET_TEXT ---",
            "AT LEAST 75% of the terms listed below MUST appear verbatim "
            "(case-insensitive) in the final bullet_rewrites[].rewritten strings. "
            "Skills-section-only placement does NOT count — the term must be "
            "woven into an experience or project bullet.",
            "",
            "CRITICAL HIGH-PRIORITY TERMS (never omit these):",
            ", ".join(high_must) if high_must else "(none specified)",
            "",
            "TRUTHFUL-BASIS RULE: The user may not have listed every skill "
            "explicitly. If the candidate's background makes a term HIGHLY PLAUSIBLE "
            "(e.g., JavaScript for full-stack work, Java for backend roles, unit "
            "testing for any software engineer, SCRUM for Agile teams), surface it "
            "as inferred_claim and let the user accept/reject. NEVER invent projects "
            "or tools they didn't touch. DO surface universal practices that fit "
            "their role family.",
            "",
            "WEAVING STRATEGY: For each term, find a bullet it naturally fits "
            "(JavaScript in a full-stack project, unit testing in backend work, "
            "SCRUM in team collaboration context). Rewrite that bullet to include "
            "the term naturally (not appended). Preserve metrics and scope.",
            "",
            "MUST_SURFACE_TERMS:",
            ", ".join(must_surface),
        ])
        if role_family:
            user_parts.extend([
                "",
                f"ROLE_FAMILY_HINT: Position the candidate as a {role_family} "
                "engineer in the summary and overall_strategy. Re-anchor 1-2 "
                "bullets per top section to match this role family.",
                "",
                "TECHNOLOGY_WEAVING_RULES (strict):",
                "- If a bullet mentions React, Next.js, or frontend work, JavaScript MUST be in the same bullet.",
                "- If a bullet mentions Java, Spring, or backend services, Java MUST be in the same bullet.",
                "- If a bullet mentions testing, TDD, or QA, unit testing MUST be mentioned.",
                "- If a bullet mentions teams, sprints, ceremonies, or Agile, SCRUM MUST be mentioned.",
                "- If a bullet describes architecture, design, or full lifecycle work, SDLC MUST be mentioned.",
                "- If a bullet mentions code review, peer feedback, or team practices, peer reviews MUST be mentioned.",
                "- If a bullet describes UI, frontend, or user interaction, web applications or web-based MUST be mentioned.",
            ])

    if score is not None:
        user_parts.extend([
            "",
            f"Current algorithmic match score: {score:.0f}/100",
        ])
    if breakdown:
        # Include key breakdown categories for context
        relevant = {
            k: v for k, v in breakdown.items()
            if k not in ("category_maxes", "skills_detail", "experience_detail",
                         "max_possible", "resume_not_uploaded")
            and isinstance(v, (int, float))
        }
        if relevant:
            maxes = breakdown.get("category_maxes", {})
            score_lines = [
                f"  {k}: {v}/{maxes.get(k, '?')}" for k, v in relevant.items()
            ]
            user_parts.append("Score breakdown:\n" + "\n".join(score_lines))

        skills_detail = breakdown.get("skills_detail", {})
        matched = skills_detail.get("matched", [])
        if matched:
            user_parts.append(f"Matched skills: {', '.join(matched)}")

    user_prompt = "\n".join(user_parts)

    async def _invoke(prompt: str) -> dict:
        res = await generate_message(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=prompt,
            max_tokens=4096,
        )
        raw_out = res.get("draft", "")
        if raw_out.startswith("```"):
            lines = [ln for ln in raw_out.split("\n") if not ln.strip().startswith("```")]
            raw_out = "\n".join(lines)
        try:
            return {"parsed": json.loads(raw_out), "result": res, "raw": raw_out}
        except json.JSONDecodeError:
            return {"parsed": None, "result": res, "raw": raw_out}

    first = await _invoke(user_prompt)
    parsed = first["parsed"]
    result = first["result"]
    raw = first["raw"]

    # Enforce coverage floor: every experience index 0..2 and every present
    # project index 0..2 gets >=2 rewrites; >=5 inferred_claim across sections;
    # >=3 keyword rewrites. Retry ONCE with explicit deficits when unmet.
    for _attempt in range(3):
        if not (parsed and isinstance(parsed.get("bullet_rewrites"), list)):
            break
        deficits = _coverage_deficits(
            parsed.get("bullet_rewrites") or [], profile, must_surface=must_surface,
        )
        if not deficits:
            break
        retry_prompt = (
            user_prompt
            + "\n\nPREVIOUS OUTPUT MISSED COVERAGE. Fix every gap below and return a "
            "complete REPLACEMENT JSON (not a diff). Do not drop prior rewrites; "
            "add whatever is needed on top:\n"
            + "\n".join(f"- {d}" for d in deficits)
        )
        retry = await _invoke(retry_prompt)
        if retry["parsed"]:
            parsed = retry["parsed"]
            result = retry["result"]
            raw = retry["raw"]

    if parsed is None:
        logger.warning("Failed to parse resume tailoring JSON, returning raw")
        parsed = {
            "summary": raw[:500] if raw else "Unable to generate tailoring suggestions.",
            "skills_to_emphasize": [],
            "skills_to_add": [],
            "keywords_to_add": [],
            "bullet_rewrites": [],
            "section_suggestions": [],
            "overall_strategy": raw or "",
        }

    # Normalize and validate structure
    return {
        "summary": parsed.get("summary", ""),
        "skills_to_emphasize": parsed.get("skills_to_emphasize", []),
        "skills_to_add": parsed.get("skills_to_add", []),
        "keywords_to_add": parsed.get("keywords_to_add", []),
        "bullet_rewrites": _normalize_bullet_rewrites(parsed.get("bullet_rewrites", [])),
        "section_suggestions": parsed.get("section_suggestions", []),
        "overall_strategy": parsed.get("overall_strategy", ""),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "usage": result.get("usage"),
    }
