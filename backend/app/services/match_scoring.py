"""Enhanced job-resume match scoring engine.

Scores jobs against a user's profile and parsed resume using multi-axis
algorithmic matching. No LLM calls — fast enough for batch scoring.
"""

from __future__ import annotations

import re

from app.models.profile import Profile

# ---------------------------------------------------------------------------
# Skill synonyms — map common aliases to a canonical form
# ---------------------------------------------------------------------------

_SKILL_SYNONYMS: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "c++": "cpp",
    "c#": "csharp",
    "react.js": "react",
    "reactjs": "react",
    "react js": "react",
    "next.js": "nextjs",
    "next js": "nextjs",
    "node.js": "nodejs",
    "node js": "nodejs",
    "nodej": "nodejs",
    "vue.js": "vue",
    "vuejs": "vue",
    "angular.js": "angular",
    "angularjs": "angular",
    "express.js": "express",
    "expressjs": "express",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "k8s": "kubernetes",
    "tf": "terraform",
    "gcp": "google cloud",
    "google cloud platform": "google cloud",
    "aws": "amazon web services",
    "amazon web services": "aws",
    "azure": "microsoft azure",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "dynamodb": "dynamo db",
    "dynamo db": "dynamodb",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "rest api": "rest",
    "restful": "rest",
    "graphql": "graphql",
    "sql server": "mssql",
    "ms sql": "mssql",
    "scikit-learn": "sklearn",
    "scikit learn": "sklearn",
    "pytorch": "pytorch",
    "tensorflow": "tensorflow",
    "html5": "html",
    "css3": "css",
    "sass": "scss",
    "tailwind css": "tailwind",
    "tailwindcss": "tailwind",
    "shell scripting": "bash",
    "shell": "bash",
    "data science": "data science",
    "data engineering": "data engineering",
    "data analytics": "data analytics",
    "oop": "object oriented programming",
    "object-oriented": "object oriented programming",
    "swe": "software engineering",
    "devops": "devops",
    "sre": "site reliability engineering",
    "qa": "quality assurance",
    "ui/ux": "ux design",
    "ui ux": "ux design",
    "figma": "figma",
    "tableau": "tableau",
    "power bi": "powerbi",
    "excel": "excel",
    "r": "rlang",
}

# Skills that are too short/generic to substring-match safely
_UNSAFE_SUBSTRING_SKILLS = frozenset({
    "r", "c", "go", "ai", "ml", "dl", "qa", "ui", "ux", "it", "bi",
    "ci", "cd", "db", "os", "pm", "api", "sql", "css", "git", "npm",
    "vue", "aws", "gcp", "ios", "iot", "sas", "crm", "erp",
})

# Reverse synonym map: canonical -> all aliases (including itself)
_CANONICAL_TO_ALIASES: dict[str, set[str]] = {}
for _alias, _canon in _SKILL_SYNONYMS.items():
    _CANONICAL_TO_ALIASES.setdefault(_canon, {_canon}).add(_alias)

# Word-boundary pattern cache
_WORD_BOUNDARY_CACHE: dict[str, re.Pattern] = {}


def _word_boundary_pattern(term: str) -> re.Pattern:
    """Get or create a word-boundary regex for a skill term."""
    if term not in _WORD_BOUNDARY_CACHE:
        escaped = re.escape(term)
        _WORD_BOUNDARY_CACHE[term] = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return _WORD_BOUNDARY_CACHE[term]


def _canonicalize_skill(skill: str) -> str:
    """Normalize a skill name to its canonical form."""
    lower = skill.lower().strip()
    return _SKILL_SYNONYMS.get(lower, lower)


def _canonicalize_skills(skills: list[str]) -> set[str]:
    """Normalize a list of skills to canonical forms."""
    return {_canonicalize_skill(s) for s in skills if s.strip()}


def _term_in_text(term: str, text_lower: str) -> bool:
    """Check if a single term appears in lowered text."""
    if term in _UNSAFE_SUBSTRING_SKILLS or len(term) <= 3:
        return bool(_word_boundary_pattern(term).search(text_lower))
    return term in text_lower


def _skill_in_text(skill: str, text: str) -> bool:
    """Check if a skill (or any of its synonyms) appears in text."""
    canonical = _canonicalize_skill(skill)
    text_lower = text.lower()
    # Check canonical form + all known aliases
    aliases = _CANONICAL_TO_ALIASES.get(canonical, {canonical})
    return any(_term_in_text(a, text_lower) for a in aliases)


# ---------------------------------------------------------------------------
# JD requirement extraction
# ---------------------------------------------------------------------------

_REQUIREMENT_HEADERS = re.compile(
    r"(?:requirements?|qualifications?|must[- ]have|what (?:you|we)(?:'re| are) looking for"
    r"|who you are|what you(?:'ll)? bring|minimum qualifications?)",
    re.IGNORECASE,
)

_NICE_TO_HAVE_HEADERS = re.compile(
    r"(?:nice[- ]to[- ]have|preferred|bonus|plus|desired|additional)",
    re.IGNORECASE,
)


def _extract_jd_sections(description: str) -> dict:
    """Parse a job description into requirement/nice-to-have sections.

    Returns dict with keys: 'requirements_text', 'nice_to_have_text', 'full_text'.
    """
    if not description:
        return {"requirements_text": "", "nice_to_have_text": "", "full_text": ""}

    lines = description.split("\n")
    section = "general"
    sections: dict[str, list[str]] = {
        "general": [],
        "requirements": [],
        "nice_to_have": [],
    }

    for line in lines:
        stripped = line.strip()
        if _REQUIREMENT_HEADERS.search(stripped):
            section = "requirements"
        elif _NICE_TO_HAVE_HEADERS.search(stripped):
            section = "nice_to_have"
        sections[section].append(stripped)

    return {
        "requirements_text": " ".join(sections["requirements"]).lower(),
        "nice_to_have_text": " ".join(sections["nice_to_have"]).lower(),
        "full_text": description.lower(),
    }


# ---------------------------------------------------------------------------
# Title matching helpers
# ---------------------------------------------------------------------------

_TITLE_SYNONYMS: dict[str, set[str]] = {
    "software engineer": {"software developer", "swe", "software eng", "dev"},
    "software developer": {"software engineer", "swe", "software eng", "dev"},
    "frontend engineer": {"front end engineer", "frontend developer", "front-end"},
    "backend engineer": {"back end engineer", "backend developer", "back-end"},
    "full stack engineer": {"fullstack engineer", "full-stack developer", "fullstack developer"},
    "data scientist": {"data science", "ds"},
    "data engineer": {"data engineering"},
    "data analyst": {"data analytics", "business analyst"},
    "machine learning engineer": {"ml engineer", "mle", "ai engineer"},
    "product manager": {"pm", "product management"},
    "devops engineer": {"devops", "sre", "site reliability engineer", "platform engineer"},
    "qa engineer": {"quality assurance", "test engineer", "sdet"},
    "ux designer": {"ui/ux designer", "product designer", "ux design"},
}


def _normalize_title(title: str) -> set[str]:
    """Expand a title into itself + synonym variants."""
    lower = title.lower().strip()
    variants = {lower}
    for canonical, syns in _TITLE_SYNONYMS.items():
        if lower == canonical or lower in syns:
            variants.add(canonical)
            variants.update(syns)
    return variants


# ---------------------------------------------------------------------------
# Experience level mapping
# ---------------------------------------------------------------------------

_YEARS_PATTERN = re.compile(
    r"(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp)?",
    re.IGNORECASE,
)


def _extract_years_required(text: str) -> int | None:
    """Extract minimum years of experience from JD text."""
    matches = _YEARS_PATTERN.findall(text)
    if matches:
        return min(int(m) for m in matches)
    return None


def _estimate_user_years(experience: list[dict]) -> float:
    """Estimate total years of work experience from parsed resume."""
    if not experience:
        return 0.0
    return float(len(experience))  # rough: 1 entry ≈ 1+ year


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

# Score weights (total = 100)
_W_SKILLS = 35
_W_EXPERIENCE = 25
_W_ROLE = 20
_W_LOCATION = 10
_W_EDUCATION = 5
_W_LEVEL = 5


def score_job(job_data: dict, profile: Profile | None) -> tuple[float, dict]:
    """Score a job against the user's profile and parsed resume.

    Returns:
        (score 0-100, breakdown dict with per-axis scores and metadata)
    """
    if not profile:
        return 0.0, {"resume_not_uploaded": True}

    title = (job_data.get("title") or "").lower()
    description = (job_data.get("description") or "")
    location = (job_data.get("location") or "").lower()
    is_remote = bool(job_data.get("remote"))

    jd = _extract_jd_sections(description)
    full_text = jd["full_text"]
    req_text = jd["requirements_text"] or full_text

    breakdown: dict[str, object] = {}

    # -----------------------------------------------------------------------
    # 1. Skills match (0-35 points)
    # -----------------------------------------------------------------------
    skills_score = 0.0
    skills_detail: dict[str, object] = {"matched": [], "total_resume_skills": 0}

    resume_skills = []
    if profile.resume_parsed and profile.resume_parsed.get("skills"):
        resume_skills = profile.resume_parsed["skills"]

    if resume_skills:
        canonical_resume = _canonicalize_skills(resume_skills)
        skills_detail["total_resume_skills"] = len(canonical_resume)

        matched = []
        for skill in canonical_resume:
            # Check in requirements section first (higher weight), then full text
            if _skill_in_text(skill, req_text):
                matched.append(skill)
            elif _skill_in_text(skill, full_text):
                matched.append(skill)

        skills_detail["matched"] = matched
        match_ratio = len(matched) / max(len(canonical_resume), 1)
        # Scale: 50%+ match = full score, below is proportional
        skills_score = min(_W_SKILLS, match_ratio * _W_SKILLS * 2)

    breakdown["skills_match"] = round(skills_score, 1)
    breakdown["skills_detail"] = skills_detail

    # -----------------------------------------------------------------------
    # 2. Experience relevance (0-25 points)
    # -----------------------------------------------------------------------
    exp_score = 0.0
    exp_detail: dict[str, object] = {}

    experience = []
    if profile.resume_parsed and profile.resume_parsed.get("experience"):
        experience = profile.resume_parsed["experience"]

    if experience:
        # Check title overlap between resume jobs and target job
        target_variants = _normalize_title(job_data.get("title", ""))
        title_matches = 0
        relevant_companies = 0

        for entry in experience:
            entry_title = (entry.get("title") or "").lower()
            entry_desc = (entry.get("description") or "").lower()
            entry_company = (entry.get("company") or "").lower()

            # Title similarity
            entry_variants = _normalize_title(entry_title)
            if entry_variants & target_variants:
                title_matches += 1
            elif any(v in entry_title for v in target_variants if len(v) > 3):
                title_matches += 0.5

            # Domain/industry overlap via description keywords
            if any(word in entry_desc for word in title.split() if len(word) > 3):
                relevant_companies += 1

            # Same company experience
            target_company = (job_data.get("company_name") or "").lower()
            if target_company and entry_company and target_company in entry_company:
                relevant_companies += 2

        title_relevance = min(1.0, title_matches / max(len(experience), 1) * 2)
        company_relevance = min(1.0, relevant_companies / max(len(experience), 1))

        exp_score = (title_relevance * _W_EXPERIENCE * 0.7) + (company_relevance * _W_EXPERIENCE * 0.3)
        exp_detail["title_relevance"] = round(title_relevance, 2)
        exp_detail["entry_count"] = len(experience)
    else:
        exp_detail["no_experience"] = True

    breakdown["experience_match"] = round(exp_score, 1)
    breakdown["experience_detail"] = exp_detail

    # -----------------------------------------------------------------------
    # 3. Role match (0-20 points)
    # -----------------------------------------------------------------------
    role_score = 0.0

    if profile.target_roles:
        best_role_score = 0.0
        for role in profile.target_roles:
            role_variants = _normalize_title(role)
            # Exact title match
            if any(v in title for v in role_variants if len(v) > 3):
                best_role_score = max(best_role_score, _W_ROLE)
            # Appears in description
            elif any(v in full_text for v in role_variants if len(v) > 3):
                best_role_score = max(best_role_score, _W_ROLE * 0.5)
        role_score = best_role_score

    breakdown["role_match"] = round(role_score, 1)

    # -----------------------------------------------------------------------
    # 4. Location match (0-10 points)
    # -----------------------------------------------------------------------
    location_score = 0.0

    if profile.target_locations:
        for loc in profile.target_locations:
            if loc.lower() in location:
                location_score = float(_W_LOCATION)
                break
        if is_remote:
            location_score = max(location_score, _W_LOCATION * 0.8)
    elif is_remote:
        location_score = _W_LOCATION * 0.7

    breakdown["location_match"] = round(location_score, 1)

    # -----------------------------------------------------------------------
    # 5. Education fit (0-5 points)
    # -----------------------------------------------------------------------
    edu_score = 0.0
    education = []
    if profile.resume_parsed and profile.resume_parsed.get("education"):
        education = profile.resume_parsed["education"]

    if education:
        # Basic: having education entries = baseline
        edu_score = _W_EDUCATION * 0.4

        for entry in education:
            field = (entry.get("field") or "").lower()
            degree = (entry.get("degree") or "").lower()

            # Check if field of study matches JD
            if field and field in full_text:
                edu_score = max(edu_score, _W_EDUCATION * 0.8)

            # Advanced degree bonus
            if any(kw in degree for kw in ("master", "ms ", "m.s.", "phd", "ph.d.", "doctorate")):
                if any(kw in full_text for kw in ("master", "ms ", "m.s.", "phd", "ph.d.", "advanced degree")):
                    edu_score = float(_W_EDUCATION)

    breakdown["education_match"] = round(edu_score, 1)

    # -----------------------------------------------------------------------
    # 6. Experience level fit (0-5 points)
    # -----------------------------------------------------------------------
    level_score = _W_LEVEL * 0.5  # default middle ground
    inferred_level = job_data.get("experience_level", "")
    user_years = _estimate_user_years(experience)

    years_required = _extract_years_required(req_text)
    if years_required is not None:
        if user_years >= years_required:
            level_score = float(_W_LEVEL)
        elif user_years >= years_required * 0.7:
            level_score = _W_LEVEL * 0.7
        else:
            level_score = _W_LEVEL * 0.3
    elif inferred_level in ("intern", "new_grad"):
        # Entry level favors less experience
        if user_years <= 3:
            level_score = float(_W_LEVEL)
        else:
            level_score = _W_LEVEL * 0.6
    elif inferred_level == "senior":
        if user_years >= 4:
            level_score = float(_W_LEVEL)
        else:
            level_score = _W_LEVEL * 0.3

    breakdown["level_fit"] = round(level_score, 1)

    # -----------------------------------------------------------------------
    # Total
    # -----------------------------------------------------------------------
    total = (
        skills_score + exp_score + role_score
        + location_score + edu_score + level_score
    )

    # Compute summary fields for the frontend
    breakdown["max_possible"] = 100
    breakdown["category_maxes"] = {
        "skills_match": _W_SKILLS,
        "experience_match": _W_EXPERIENCE,
        "role_match": _W_ROLE,
        "location_match": _W_LOCATION,
        "education_match": _W_EDUCATION,
        "level_fit": _W_LEVEL,
    }

    return round(total, 1), breakdown


# ---------------------------------------------------------------------------
# LLM deep analysis (on-demand, not batch)
# ---------------------------------------------------------------------------

async def deep_analyze_match(
    job_data: dict,
    profile: Profile,
    score: float,
    breakdown: dict,
) -> dict:
    """Use LLM to produce human-readable match analysis.

    Returns:
        {
            "summary": str,
            "strengths": [str],
            "gaps": [str],
            "recommendations": [str],
            "model": str,
        }
    """
    from app.clients.llm_client import generate_message  # noqa: PLC0415

    resume_skills = []
    experience = []
    education = []
    if profile.resume_parsed:
        resume_skills = profile.resume_parsed.get("skills", [])
        experience = profile.resume_parsed.get("experience", [])
        education = profile.resume_parsed.get("education", [])

    system_prompt = (
        "You are a career match analyst. Given a job description and a candidate's "
        "resume data, produce a concise match analysis.\n\n"
        "Output EXACTLY this JSON structure (no markdown fences):\n"
        '{"summary": "2-3 sentence overall fit assessment",'
        '"strengths": ["strength 1", "strength 2", ...],'
        '"gaps": ["gap 1", "gap 2", ...],'
        '"recommendations": ["recommendation 1", "recommendation 2", ...]}\n\n'
        "Rules:\n"
        "- Be specific. Reference actual skills, roles, and requirements.\n"
        "- Strengths: what the candidate already has that the job wants.\n"
        "- Gaps: what the job requires that the candidate lacks.\n"
        "- Recommendations: concrete actions to improve fit (courses, projects, framing).\n"
        "- Keep each list to 3-5 items max.\n"
        "- Do NOT fabricate or assume skills not listed in the resume."
    )

    experience_summary = ""
    for exp in experience[:5]:
        exp_title = exp.get("title", "")
        exp_company = exp.get("company", "")
        exp_desc = (exp.get("description") or "")[:200]
        experience_summary += f"- {exp_title} at {exp_company}: {exp_desc}\n"

    education_summary = ""
    for edu in education[:3]:
        edu_degree = edu.get("degree", "")
        edu_field = edu.get("field", "")
        edu_inst = edu.get("institution", "")
        education_summary += f"- {edu_degree} in {edu_field} from {edu_inst}\n"

    user_prompt = (
        f"## Job\n"
        f"Title: {job_data.get('title', '')}\n"
        f"Company: {job_data.get('company_name', '')}\n"
        f"Location: {job_data.get('location', '')}\n"
        f"Level: {job_data.get('experience_level', 'not specified')}\n\n"
        f"Description:\n{(job_data.get('description') or '')[:3000]}\n\n"
        f"## Candidate\n"
        f"Target roles: {', '.join(profile.target_roles or [])}\n"
        f"Skills: {', '.join(resume_skills[:30])}\n\n"
        f"Experience:\n{experience_summary}\n"
        f"Education:\n{education_summary}\n"
        f"## Current Match Score: {score}/100\n"
        f"Breakdown: {breakdown}\n"
    )

    import json  # noqa: PLC0415
    result = await generate_message(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=800,
    )

    draft_text = result.get("draft", "")
    # Strip markdown code fences if present
    draft_text = draft_text.strip()
    if draft_text.startswith("```"):
        draft_text = re.sub(r"^```(?:json)?\s*", "", draft_text)
        draft_text = re.sub(r"\s*```$", "", draft_text)

    try:
        analysis = json.loads(draft_text)
    except json.JSONDecodeError:
        analysis = {
            "summary": draft_text[:500],
            "strengths": [],
            "gaps": [],
            "recommendations": [],
        }

    analysis["model"] = result.get("model", "")
    analysis["usage"] = result.get("usage", {})
    return analysis
