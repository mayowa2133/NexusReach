"""AI-powered resume tailoring service.

Given a user's parsed resume and a target job, generates specific,
actionable suggestions for tailoring the resume to maximize match.
"""

from __future__ import annotations

import json
import logging
import re
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
- bullet_rewrites: selective and TRUTHFUL. Propose only edits that materially
  improve the resume. There is no minimum count: zero inferred claims is a
  completely valid result, and a sparse resume should receive only the few
  edits its evidence supports. Never rewrite a bullet merely to fill a quota.
  * MUST_SURFACE handling: if MUST_SURFACE_IN_BULLET_TEXT terms are provided (below), be THOROUGH — surface every term the candidate can TRUTHFULLY claim, woven naturally into a bullet where it fits. This includes honest reframes their real work supports (e.g. "customer-facing" for a shipped consumer feature, "cross-functional" for Agile team work, "frontend" for someone who built UI). Leaving a truthful, matchable term unsurfaced is a miss. The ONLY terms to skip are those that would be false — a platform the candidate never worked on, or a tool they never used. Never drop a term the candidate clearly has once surfaced.
  For experience bullets, set section="experience" and provide experience_index. For project bullets, set section="projects" and provide project_index. Use quantified achievements where possible.
- Classify every rewrite's change_type with this STRICT mechanical test. When uncertain, always choose the MORE gated type (inferred_claim > reframe > keyword):
  1. Read the ORIGINAL bullet, then the REWRITE.
  2. List every capability, tool, platform, methodology, scope, metric, or JD term in the REWRITE that is NOT literally present in the ORIGINAL bullet.
  3. If that list is NON-EMPTY, the rewrite is "inferred_claim" — no exceptions. Weaving in a MUST_SURFACE or JD term (e.g. "go-to-market", "customer-facing", "cross-functional", "component-based", "unit testing", "stakeholder management") is ALWAYS inferred_claim, however plausible it feels. A "sharper angle" that introduces a new term is an inferred_claim, NOT a reframe.
  - "keyword" = you only substituted a synonym for a word ALREADY in the original ("built" -> "engineered"); the list from step 2 is empty.
  - "reframe" = you re-angled the SAME facts and EVERY capability/tool/scope/term in the rewrite was ALREADY explicitly in the original; the list from step 2 is empty.
  - "inferred_claim" = the list from step 2 is non-empty (the rewrite adds at least one term/capability/scope the original did not literally state).
- For inferred_claim rewrites, list EVERY added phrase in inferred_additions and set requires_user_confirm=true. Use keyword/reframe (requires_user_confirm=false, inferred_additions=[]) ONLY when the rewrite adds nothing new.
- Surface plausible JD-adjacent terms as inferred_claim (gated for the user to confirm), NEVER as keyword/reframe. Never fabricate specific metrics or named tools the candidate did not list. Only surface capabilities and scope the candidate genuinely has a basis for.
- PLATFORM FIT (critical): match the candidate's actual platform. Do NOT add "web application"/"web-based"/"web UI" language to native mobile (iOS/Android) work, or mobile language to pure web work. A native iOS feature is an "iOS" or "mobile" feature, never a "web application". If the JD's platform differs from the candidate's, surface the transferable engineering practices (testing, architecture, collaboration) truthfully instead of claiming the wrong platform.
- NO KEYWORD STUFFING: use each term at most once, in its natural form. Never inject multiple near-duplicate variants of one keyword (e.g. "mobile-responsive", "mobile-ready", "mobile-capable", "mobile-friendly") to pad density — a recruiter reads that as spam and it weakens the resume.
- Prefer breadth when several entries have equally strong evidence, but do not
  force coverage of weak or irrelevant entries.
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
- For frontend/fullstack web roles WHERE THE CANDIDATE ACTUALLY DID WEB WORK, prefer the concise recruiter-ready style used in strong manual tailoring:
  - customer-facing product features
  - scalable, maintainable application behavior
  - RESTful APIs and client-server integration
  - telemetry, testing, debugging, and Git-based collaboration
  - responsive, component-based UI language ONLY for genuine web projects (never for native iOS/Android work)
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
    "web applications", "observability", "logging", "tracing", "metrics",
    "authentication", "documentation", "configuration", "developer experience",
    "platform engineering", "shared libraries", "SDKs", "inner-source",
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

    # Word-boundary matching: naive substring matching made short hints like
    # "Go", "XP", "C#", "R" fire inside unrelated words ("ne-go-tiate",
    # "e-xp-erience", "categor-y"), injecting junk skills into non-tech resume
    # plans and scoring. Boundaries are alphanumeric-only, so dotted/hashed
    # terms ("C#", "Next.js", "CI/CD") still match — including at a sentence
    # end where the next char is punctuation.
    def _hint_present(term: str) -> bool:
        t = re.escape(term.lower())
        if re.search(rf"(?<![a-z0-9]){t}(?![a-z0-9])", low):
            return True
        # Tolerate dotted variants written without the dot ("nextjs" ~ "next.js").
        if "." in term:
            td = re.escape(term.lower().replace(".", ""))
            return bool(re.search(rf"(?<![a-z0-9]){td}(?![a-z0-9])", low.replace(".", "")))
        return False

    tech_hits = [term for term in _TECH_HINTS if _hint_present(term)]
    method_hits = [term for term in _METHOD_HINTS if _hint_present(term)]

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
    """Return structural deficits that justify another model call.

    Rewrite volume and inferred-claim counts are deliberately *not* validation
    criteria. The old implementation required five inferred claims and three
    keyword edits even for a one-bullet resume, which encouraged fabrication.
    Content safety is enforced deterministically by normalization and by the
    artifact evidence gate; a small or empty rewrite set is valid.
    """
    return []


def _infer_change_type(original: str, rewritten: str) -> tuple[str, list[str]]:
    """Fallback classifier when the LLM omits change_type.

    Finds content words in the rewrite that do not appear in the original; if
    any, classify as inferred_claim.
    """
    import re as _re

    def _words(text: str) -> set[str]:
        return {
            w.lower().strip(".-_/")
            for w in _re.findall(r"[A-Za-z][A-Za-z0-9+.#/-]{2,}", text or "")
            if w.lower().strip(".-_/") not in {
                "the", "and", "for", "with", "that", "this", "from", "into",
                "using", "used", "our", "your", "their",
            }
        }

    original_words = _words(original)
    rewritten_words = _words(rewritten)
    new_words = sorted(rewritten_words - original_words)
    # Stylistic verbs may change without introducing a new factual claim.
    # Everything else is gated. This intentionally classifies even a single
    # new domain word ("brand", "Kubernetes", "clinical") as inferred.
    style_words = {
        "achieved", "built", "created", "delivered", "designed", "developed",
        "drove", "enabled", "engineered", "established", "executed", "improved",
        "implemented", "increased", "launched", "led", "managed", "optimized",
        "owned", "produced", "reduced", "shipped", "supported", "using", "utilized",
    }
    claim_words = [word for word in new_words if word not in style_words]
    if claim_words:
        return "inferred_claim", claim_words[:8]
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
        detected_type, auto_additions = _infer_change_type(original, rewritten)
        if change_type not in _VALID_CHANGE_TYPES:
            change_type = detected_type
        elif detected_type == "inferred_claim":
            # The model cannot downgrade a detected new claim to an ungated
            # keyword/reframe edit.
            change_type = "inferred_claim"
        if change_type == "inferred_claim" and auto_additions:
            inferred_additions = list(dict.fromkeys([
                *(str(item).strip() for item in inferred_additions if str(item).strip()),
                *auto_additions,
            ]))
        if change_type != "inferred_claim":
            inferred_additions = []

        # Inferred claims are always gated regardless of model output.
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
            "Be THOROUGH: surface every term below that the candidate can "
            "TRUTHFULLY claim, weaving each into an experience or project bullet "
            "(skills-section-only placement does not count). This includes honest "
            "reframes their real work supports (customer-facing, cross-functional, "
            "frontend for someone who built UI, etc.) — leaving a truthful, "
            "matchable term unsurfaced is a miss. Skip ONLY terms that would be "
            "false: a platform the candidate never worked on or a tool they never "
            "used. Do not stuff or repeat a term; use it once, naturally.",
            "",
            "HIGH-PRIORITY TERMS (surface if the candidate truthfully has them):",
            ", ".join(high_must) if high_must else "(none specified)",
            "",
            "TRUTHFUL-BASIS RULE: The user may not have listed every skill "
            "explicitly. If the candidate's ACTUAL background makes a term truthfully "
            "plausible (e.g., JavaScript when they list React, unit testing when they "
            "shipped production code), surface it as inferred_claim for the user to "
            "accept/reject. If a term does NOT fit their real work (e.g. a web-only "
            "term for a native-mobile candidate), leave it out entirely.",
            "",
            "WEAVING STRATEGY: For each term, find a bullet it naturally fits and "
            "rewrite that bullet to include the term naturally (not appended). "
            "Preserve metrics and scope.",
            "",
            "MUST_SURFACE_TERMS:",
            ", ".join(must_surface),
        ])
        if role_family:
            user_parts.extend([
                "",
                f"ROLE_FAMILY_HINT: Where truthful, position the candidate toward "
                f"the {role_family} role family in the summary and overall_strategy, "
                "re-anchoring 1-2 bullets per top section — but only using terms "
                "their real experience supports.",
                "",
                "TECHNOLOGY_WEAVING_RULES (apply only where truthful for THIS candidate):",
                "- If a bullet mentions React/Next.js/frontend work, JavaScript may join the same bullet.",
                "- If a bullet mentions Java/Spring/backend services, Java may join the same bullet.",
                "- If a bullet mentions testing/TDD/QA, unit testing may be surfaced.",
                "- If a bullet mentions teams/sprints/ceremonies/Agile, SCRUM may be surfaced.",
                "- Do NOT add web-platform terms to native mobile work, or mobile terms to pure web work.",
                "- Never repeat near-duplicate variants of a term to inflate density.",
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

    # Retry only for structural deficits. Rewrite-count and inferred-claim
    # quotas are intentionally absent; a truthful result may contain no edits.
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
