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
      "original": "original bullet text",
      "rewritten": "improved bullet text",
      "reason": "why this change helps",
      "experience_index": 0
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
- bullet_rewrites: rewrite 3-5 of the most impactful experience bullets to better align with the JD. Use quantified achievements where possible. experience_index refers to the 0-based index of the experience entry.
- section_suggestions: high-level guidance for each resume section
- Be specific and actionable, not generic
- Do NOT fabricate experience or skills the candidate doesn't have
- Focus on reframing existing experience to match job language
- Keep the candidate's authentic voice
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
            desc = exp.get("description", "")
            parts.append(f"  [{i}] {title} at {company} ({start} - {end})")
            if desc:
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
            desc = proj.get("description", "")
            techs = proj.get("technologies", [])
            parts.append(f"  {name}: {desc}")
            if techs:
                parts.append(f"    Technologies: {', '.join(techs)}")

    # Target roles/locations from profile
    if profile.target_roles:
        parts.append(f"\nTARGET ROLES: {', '.join(profile.target_roles)}")
    if profile.target_locations:
        parts.append(f"TARGET LOCATIONS: {', '.join(profile.target_locations)}")

    return "\n".join(parts) if parts else "(no resume data)"


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

    # Build user prompt with optional score context
    user_parts = [
        "Analyze this resume against the job posting and provide tailoring suggestions.",
        "",
        "--- CANDIDATE RESUME ---",
        resume_ctx,
        "",
        "--- TARGET JOB ---",
        job_ctx,
    ]

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

    result = await generate_message(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=2048,
    )

    # Parse the JSON from LLM response
    raw = result.get("draft", "")

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [line for line in lines if not line.strip().startswith("```")]
        raw = "\n".join(lines)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
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
        "bullet_rewrites": parsed.get("bullet_rewrites", []),
        "section_suggestions": parsed.get("section_suggestions", []),
        "overall_strategy": parsed.get("overall_strategy", ""),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "usage": result.get("usage"),
    }
