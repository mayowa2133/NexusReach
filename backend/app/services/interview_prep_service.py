"""Interview-Prep Workspace service.

Deterministic, explainable brief generation for a (user, job). No LLM call
in v1 — the goal is an honest prep scaffold that maps the job + story bank
into categories and themes. Everything the generator adds is flagged
`inferred=True`; signals pulled verbatim from the job posting are returned
under `sourced_signals` so the UI can distinguish them.
"""

from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.interview_prep_brief import InterviewPrepBrief
from app.models.job import Job
from app.services.story_service import list_stories


# ---------- generator helpers ----------


_TECH_KEYWORDS = (
    "python", "java", "golang", "go", "rust", "typescript", "javascript",
    "react", "node", "aws", "gcp", "azure", "kubernetes", "docker", "sql",
    "postgres", "redis", "kafka", "ml", "llm", "ai", "data", "backend",
    "frontend", "fullstack", "platform", "infra", "devops", "mobile",
    "ios", "android", "swift", "kotlin",
)

_DESIGN_KEYWORDS = (
    "design", "architecture", "scalab", "distributed", "system",
    "microservice", "throughput", "latency",
)

_LEADERSHIP_KEYWORDS = (
    "lead", "staff", "principal", "manager", "director", "head",
    "senior", "mentor",
)


def _pick_seniority(title: str | None, experience_level: str | None) -> str:
    t = (title or "").lower()
    if experience_level in {"senior", "staff", "principal"} or any(
        k in t for k in ("staff", "principal", "lead", "head", "director")
    ):
        return "senior"
    if experience_level == "intern" or "intern" in t:
        return "intern"
    if experience_level == "new_grad" or "new grad" in t or "entry" in t:
        return "new_grad"
    if experience_level == "mid" or "mid" in t:
        return "mid"
    return "mid"


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(re.findall(r"[a-z0-9+.#]+", text.lower()))


def _make_rounds(job: Job, seniority: str) -> list[dict]:
    title = (job.title or "").lower()
    is_eng = any(k in title for k in ("engineer", "developer", "swe", "sre")) or any(
        k in _tokens(job.description) for k in _TECH_KEYWORDS
    )
    is_design_heavy = seniority == "senior" and is_eng

    rounds: list[dict] = [
        {
            "name": "Recruiter screen",
            "type": "recruiter_screen",
            "description": "Background, motivation, logistics, comp expectations.",
            "inferred": True,
        },
        {
            "name": "Hiring manager",
            "type": "behavioral",
            "description": "Role fit, past scope, team collaboration. STAR stories expected.",
            "inferred": True,
        },
    ]
    if is_eng:
        rounds.append(
            {
                "name": "Technical round",
                "type": "technical",
                "description": "Coding or practical problem solving tied to the role's stack.",
                "inferred": True,
            }
        )
    if is_design_heavy:
        rounds.append(
            {
                "name": "System design",
                "type": "system_design",
                "description": "Architect a real-world system at interview scope.",
                "inferred": True,
            }
        )
    rounds.append(
        {
            "name": "Team / values",
            "type": "behavioral",
            "description": "Culture fit, collaboration style, conflict resolution.",
            "inferred": True,
        }
    )
    return rounds


def _make_categories(job: Job, seniority: str) -> list[dict]:
    desc_tokens = _tokens(job.description)
    cats: list[dict] = [
        {
            "key": "behavioral",
            "label": "Behavioral / STAR",
            "examples": [
                "Tell me about a time you shipped something under tight constraints.",
                "Describe a conflict with a teammate and how you resolved it.",
                "Walk me through your most impactful project.",
            ],
            "inferred": True,
        }
    ]
    if any(k in desc_tokens for k in _TECH_KEYWORDS):
        cats.append(
            {
                "key": "technical",
                "label": "Technical depth",
                "examples": [
                    f"Deep-dive on {job.title}-relevant fundamentals.",
                    "Debug or optimize a realistic code sample.",
                    "Trade-offs between the core technologies listed in the posting.",
                ],
                "inferred": True,
            }
        )
    if seniority == "senior" or any(k in desc_tokens for k in _DESIGN_KEYWORDS):
        cats.append(
            {
                "key": "system_design",
                "label": "System design",
                "examples": [
                    "Design a core product surface for the company.",
                    "Scale a feature 100x; discuss bottlenecks and mitigations.",
                    "Discuss consistency vs availability trade-offs for a realistic flow.",
                ],
                "inferred": True,
            }
        )
    cats.append(
        {
            "key": "culture_fit",
            "label": "Culture + motivation",
            "examples": [
                f"Why {job.company_name}?",
                "How do you handle ambiguity?",
                "What does a great teammate look like to you?",
            ],
            "inferred": True,
        }
    )
    cats.append(
        {
            "key": "role_specific",
            "label": "Role-specific",
            "examples": [
                f"Walk through how you'd approach week 1 in {job.title}.",
                "What from your background maps to this role?",
            ],
            "inferred": True,
        }
    )
    return cats


def _make_themes(job: Job, seniority: str) -> list[dict]:
    themes: list[dict] = []
    title_lower = (job.title or "").lower()
    if seniority == "senior" or any(k in title_lower for k in _LEADERSHIP_KEYWORDS):
        themes.append(
            {
                "title": "Lead-by-influence examples",
                "reason": "Senior / lead scope — prepare ownership and cross-team stories.",
                "inferred": True,
            }
        )
    if job.tags and any("startup" in (t or "").lower() for t in job.tags):
        themes.append(
            {
                "title": "Startup-scrappy impact",
                "reason": "Startup-tagged role — emphasize speed, breadth, ambiguity.",
                "inferred": True,
            }
        )
    themes.append(
        {
            "title": f"Concrete wins tied to {job.title}",
            "reason": "Lead each behavioral answer with a quantified impact metric.",
            "inferred": True,
        }
    )
    themes.append(
        {
            "title": f"Why {job.company_name}",
            "reason": "Have a crisp, specific reason tied to product, team, or mission.",
            "inferred": True,
        }
    )
    return themes


def _map_stories(categories: list[dict], stories) -> list[dict]:
    """Map each category to relevant stories by tag / role_focus overlap."""
    role_hints = {"behavioral", "leadership", "conflict", "recovery", "failure"}
    tech_hints = {"technical", "technical depth", "migration", "platform", "infra"}
    design_hints = {"system design", "architecture", "scale", "migration"}
    culture_hints = {"culture", "motivation", "values"}

    def match(story, wanted: set[str]) -> bool:
        tags = {t.lower() for t in (story.tags or []) if isinstance(t, str)}
        return bool(wanted & tags)

    mapping: list[dict] = []
    for cat in categories:
        key = cat["key"]
        wanted: set[str]
        if key == "behavioral":
            wanted = role_hints
        elif key == "technical":
            wanted = tech_hints
        elif key == "system_design":
            wanted = design_hints
        elif key == "culture_fit":
            wanted = culture_hints
        else:
            wanted = set()
        matched = [str(s.id) for s in stories if match(s, wanted)]
        if not matched and stories:
            matched = [str(s.id) for s in stories[:2]]
        mapping.append({"category": key, "story_ids": matched[:5]})
    return mapping


def _company_overview(company: Company | None, job: Job) -> str | None:
    if company and getattr(company, "description", None):
        return company.description
    return None


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _role_summary(job: Job) -> str | None:
    if not job.description:
        return None
    text = _HTML_TAG_RE.sub(" ", job.description)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > 600:
        return text[:600].rsplit(" ", 1)[0] + "…"
    return text


def _sourced_signals(job: Job) -> dict:
    return {
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "remote": job.remote,
        "experience_level": job.experience_level,
        "employment_type": job.employment_type,
        "has_description": bool(job.description),
        "tags": list(job.tags or []),
    }


# ---------- public service API ----------


@dataclass
class _GenerationResult:
    company_overview: str | None
    role_summary: str | None
    likely_rounds: list[dict]
    question_categories: list[dict]
    prep_themes: list[dict]
    story_map: list[dict]
    sourced_signals: dict


async def _generate(db: AsyncSession, *, user_id: uuid.UUID, job: Job) -> _GenerationResult:
    company: Company | None = None
    if job.company_id:
        company = (
            await db.execute(select(Company).where(Company.id == job.company_id))
        ).scalar_one_or_none()

    seniority = _pick_seniority(job.title, job.experience_level)
    rounds = _make_rounds(job, seniority)
    categories = _make_categories(job, seniority)
    themes = _make_themes(job, seniority)
    stories = await list_stories(db, user_id=user_id)
    story_map = _map_stories(categories, stories)

    return _GenerationResult(
        company_overview=_company_overview(company, job),
        role_summary=_role_summary(job),
        likely_rounds=rounds,
        question_categories=categories,
        prep_themes=themes,
        story_map=story_map,
        sourced_signals=_sourced_signals(job),
    )


async def get_brief(
    db: AsyncSession, *, user_id: uuid.UUID, job_id: uuid.UUID
) -> InterviewPrepBrief | None:
    result = await db.execute(
        select(InterviewPrepBrief).where(
            InterviewPrepBrief.user_id == user_id,
            InterviewPrepBrief.job_id == job_id,
        )
    )
    return result.scalar_one_or_none()


async def generate_or_refresh_brief(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    regenerate: bool = False,
) -> InterviewPrepBrief | None:
    job_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        return None

    existing = await get_brief(db, user_id=user_id, job_id=job_id)
    if existing and not regenerate:
        return existing

    gen = await _generate(db, user_id=user_id, job=job)

    if existing:
        existing.company_overview = gen.company_overview
        existing.role_summary = gen.role_summary
        existing.likely_rounds = gen.likely_rounds
        existing.question_categories = gen.question_categories
        existing.prep_themes = gen.prep_themes
        existing.story_map = gen.story_map
        existing.sourced_signals = gen.sourced_signals
        from sqlalchemy import func as sa_func

        existing.generated_at = sa_func.now()
        await db.commit()
        await db.refresh(existing)
        return existing

    brief = InterviewPrepBrief(
        user_id=user_id,
        job_id=job_id,
        company_overview=gen.company_overview,
        role_summary=gen.role_summary,
        likely_rounds=gen.likely_rounds,
        question_categories=gen.question_categories,
        prep_themes=gen.prep_themes,
        story_map=gen.story_map,
        sourced_signals=gen.sourced_signals,
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return brief


async def update_brief(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    user_notes: str | None = None,
    story_map: list[dict] | None = None,
) -> InterviewPrepBrief | None:
    brief = await get_brief(db, user_id=user_id, job_id=job_id)
    if brief is None:
        return None
    if user_notes is not None:
        brief.user_notes = user_notes
    if story_map is not None:
        brief.story_map = story_map
    await db.commit()
    await db.refresh(brief)
    return brief


async def delete_brief(
    db: AsyncSession, *, user_id: uuid.UUID, job_id: uuid.UUID
) -> bool:
    brief = await get_brief(db, user_id=user_id, job_id=job_id)
    if brief is None:
        return False
    await db.delete(brief)
    await db.commit()
    return True
