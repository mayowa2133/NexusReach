"""Resume artifact persistence and orchestration."""

from __future__ import annotations

import logging
import uuid
import hashlib
import json
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.profile import Profile
from app.models.resume_artifact import ResumeArtifact
from app.models.settings import UserSettings
from app.models.tailored_resume import TailoredResume
from app.models.user import User
from app.services.match_scoring import score_job
from app.services.resume_tailor import (
    TAILORING_PROMPT_VERSION,
    _normalize_bullet_rewrites,
    tailor_resume,
)
from app.services.resume_artifact.latex import (
    _render_resume_latex,
    render_resume_artifact_pdf_async,
    verify_rendered_resume_pdf,
)
from app.services.resume_artifact.parsed import _extract_resume_data
from app.services.resume_artifact.plan import _build_resume_artifact_plan, _job_family, score_resume_content_against_job
from app.services.resume_artifact.quality import (
    RUBRIC_VERSION,
    evaluate_resume_quality,
    quality_planner_guidance,
    unavailable_quality_evaluation,
)
from app.services.resume_artifact.textnorm import (
    _latex_plain_text,
    _resume_body_contains_term,
    _slugify_label,
)
from app.services.job_requirements import extract_job_requirements
from app.services.resume_artifact.truthfulness import (
    build_truthfulness_ledger,
    validate_truthfulness_ledger,
)

logger = logging.getLogger(__name__)


RESUME_REUSE_SCORE_THRESHOLD = 80.0
RESUME_REUSE_QUALITY_THRESHOLD = 70.0


def tailoring_input_hash(*, profile: Profile, job: Job) -> str:
    """Hash every input that can change generated tailoring semantics."""
    payload = {
        "resume": getattr(profile, "resume_parsed", None) or getattr(profile, "resume_raw", None) or "",
        "job": {
            "title": job.title,
            "company_name": job.company_name,
            "description": job.description or "",
            "experience_level": getattr(job, "experience_level", None),
            "tags": getattr(job, "tags", None) or [],
        },
        "prompt_version": TAILORING_PROMPT_VERSION,
        "rubric_version": RUBRIC_VERSION,
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _render_qa(content: str) -> dict[str, Any]:
    """Render and independently verify before an artifact can be persisted."""
    pdf_bytes = await render_resume_artifact_pdf_async(content)
    return verify_rendered_resume_pdf(pdf_bytes, content)


def _attach_render_qa(evaluation: dict, render_qa: dict) -> dict:
    updated = dict(evaluation)
    updated["render_qa"] = render_qa
    axes = dict(updated.get("axes") or {})
    axes["parseability"] = {
        "score": 100.0,
        "max": 100,
        "evidence": [
            f"Verified {render_qa['page_count']} page with pypdf and Poppler; "
            f"parser agreement {render_qa['parser_agreement']:.1%}."
        ],
        "improvements": [],
    }
    updated["axes"] = axes
    can_recompute = all(
        isinstance(axes.get(key), dict)
        and isinstance(axes[key].get("score"), (int, float))
        for key in ("job_fit", "evidence_quality")
    )
    overall = (
        round(
            float(axes["job_fit"]["score"]) * 0.45
            + float(axes["evidence_quality"]["score"]) * 0.45
            + 10.0,
            1,
        )
        if can_recompute
        else float(updated.get("overall_score") or 0)
    )
    updated["overall_score"] = overall
    updated["readiness"] = (
        "strong" if overall >= 85
        else "competitive" if overall >= 70
        else "developing" if overall >= 50
        else "needs_work"
    )
    return updated


def _attach_truthfulness_ledger(evaluation: dict, ledger: dict) -> dict:
    updated = dict(evaluation)
    truthfulness = dict(updated.get("truthfulness") or {})
    truthfulness["ledger"] = ledger
    updated["truthfulness"] = truthfulness
    return updated


def _build_resume_reuse_candidate(
    *,
    artifact: ResumeArtifact,
    source_job: Job,
    target_job: Job,
    threshold: float,
    parsed_resume: dict[str, Any] | None = None,
    quality_threshold: float | None = None,
) -> dict[str, Any] | None:
    source_family = _job_family(source_job)
    target_family = _job_family(target_job)
    if source_family != target_family:
        return None

    level_rank = {"intern": 0, "new_grad": 0, "mid": 1, "senior": 2}
    source_level = level_rank.get(getattr(source_job, "experience_level", None))
    target_level = level_rank.get(getattr(target_job, "experience_level", None))
    if (
        source_level is not None
        and target_level is not None
        and abs(source_level - target_level) > 1
    ):
        return None

    rendered_text = _latex_plain_text(artifact.content)
    critical_requirements = [
        requirement
        for requirement in extract_job_requirements(target_job.description or "")
        if requirement.kind == "mandatory"
        and requirement.criticality == "hard"
        and requirement.evidence_type in {"credential", "license", "clearance"}
    ]
    if any(
        not _resume_body_contains_term(rendered_text, requirement.normalized)
        and not _resume_body_contains_term(rendered_text, requirement.display_text)
        for requirement in critical_requirements
    ):
        return None

    score = score_resume_content_against_job(artifact.content, target_job)
    if score is None or score < threshold:
        return None

    quality_score: float | None = None
    if parsed_resume is not None:
        try:
            evaluation = evaluate_resume_quality(
                parsed=parsed_resume,
                content=artifact.content,
                job=target_job,
            )
            evidence_axis = (evaluation.get("axes") or {}).get("evidence_quality")
            if (
                evaluation.get("status") == "ready"
                and isinstance(evidence_axis, dict)
                and isinstance(evidence_axis.get("score"), (int, float))
            ):
                quality_score = float(evidence_axis["score"])
        except Exception as exc:
            logger.warning("Resume reuse quality evaluation failed: %s", exc)
        if quality_threshold is not None and (
            quality_score is None or quality_score < quality_threshold
        ):
            return None

    return {
        "artifact": artifact,
        "source_job": source_job,
        "score": score,
        "quality_score": quality_score,
        "threshold": threshold,
        "quality_threshold": quality_threshold,
        "job_family": target_family,
        "reason": (
            f"This saved resume covers {score:.1f}% of the evaluated posting terms "
            f"and matches the {target_family.replace('_', '/')} job family."
            + (
                f" Its evidence-quality dimension is {quality_score:.1f}%."
                if quality_score is not None
                else ""
            )
        ),
    }


async def get_resume_reuse_candidates_for_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    threshold: float = RESUME_REUSE_SCORE_THRESHOLD,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find artifacts that pass deterministic compatibility and evidence gates."""
    target_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    target_job = target_result.scalar_one_or_none()
    if not target_job:
        raise ValueError("Job not found.")

    rows = await list_resume_artifacts_for_user(db=db, user_id=user_id)
    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    parsed_resume = (profile.resume_parsed or {}) if profile else {}
    candidates: list[dict[str, Any]] = []
    for artifact, source_job in rows:
        if artifact.job_id == job_id:
            continue
        candidate = _build_resume_reuse_candidate(
            artifact=artifact,
            source_job=source_job,
            target_job=target_job,
            threshold=threshold,
            parsed_resume=parsed_resume,
            quality_threshold=RESUME_REUSE_QUALITY_THRESHOLD,
        )
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            float(item["score"]),
            item["artifact"].generated_at,
        ),
        reverse=True,
    )
    return candidates[:limit]


async def get_resume_auto_reuse_enabled(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    return bool(settings and settings.resume_auto_reuse_enabled)


async def reuse_resume_artifact_for_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    source_artifact_id: uuid.UUID,
    threshold: float = RESUME_REUSE_SCORE_THRESHOLD,
) -> tuple[ResumeArtifact, Job]:
    """Copy an evidence-qualified compatible artifact onto another job."""
    target_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    target_job = target_result.scalar_one_or_none()
    if not target_job:
        raise ValueError("Job not found.")

    source_result = await db.execute(
        select(ResumeArtifact, Job)
        .join(Job, Job.id == ResumeArtifact.job_id)
        .where(
            ResumeArtifact.id == source_artifact_id,
            ResumeArtifact.user_id == user_id,
        )
    )
    source_row = source_result.one_or_none()
    if source_row is None:
        raise ValueError("Saved resume artifact not found.")

    source_artifact, source_job = source_row
    if source_artifact.job_id == job_id:
        raise ValueError("Cannot reuse a resume artifact for the same job.")

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    candidate = _build_resume_reuse_candidate(
        artifact=source_artifact,
        source_job=source_job,
        target_job=target_job,
        threshold=threshold,
        parsed_resume=(profile.resume_parsed or {}) if profile else {},
        quality_threshold=RESUME_REUSE_QUALITY_THRESHOLD,
    )
    if candidate is None:
        raise ValueError("Saved resume does not meet the reuse threshold for this job.")

    artifact_result = await db.execute(
        select(ResumeArtifact).where(
            ResumeArtifact.user_id == user_id,
            ResumeArtifact.job_id == job_id,
        )
    )
    artifact = artifact_result.scalar_one_or_none()
    if artifact is None:
        artifact = ResumeArtifact(user_id=user_id, job_id=job_id)
        db.add(artifact)

    artifact.tailored_resume_id = None
    artifact.reused_from_artifact_id = source_artifact.id
    artifact.reuse_score = float(candidate["score"])
    artifact.format = source_artifact.format
    artifact.filename = (
        f"resume-{_slugify_label(target_job.company_name, 'company')}-"
        f"{datetime.now(timezone.utc).date().isoformat()}.tex"
    )
    artifact.content = source_artifact.content
    artifact.rewrite_decisions = {}
    ledger = build_truthfulness_ledger(
        parsed=(profile.resume_parsed or {}) if profile else {},
        content=artifact.content,
        tailored=SimpleNamespace(
            skills_to_emphasize=[],
            skills_to_add=[],
            keywords_to_add=[],
            bullet_rewrites=[],
        ),
    )
    validate_truthfulness_ledger(ledger)
    render_qa = await _render_qa(artifact.content)
    try:
        evaluation = evaluate_resume_quality(
            parsed=(profile.resume_parsed or {}) if profile else {},
            content=artifact.content,
            job=target_job,
        )
    except Exception as exc:
        logger.warning("Resume quality evaluation failed during reuse: %s", exc)
        evaluation = unavailable_quality_evaluation(str(exc))
    if evaluation.get("status") == "ready":
        evaluation = _attach_render_qa(evaluation, render_qa)
    evaluation = _attach_truthfulness_ledger(evaluation, ledger)
    artifact.quality_evaluation = evaluation
    artifact.quality_score = (
        float(evaluation["overall_score"])
        if evaluation.get("status") == "ready"
        else None
    )
    artifact.generated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(artifact)
    return artifact, source_job


async def _load_or_generate_tailoring(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job: Job,
    profile: Profile,
    prefer_existing: bool = True,
) -> TailoredResume:
    input_hash = tailoring_input_hash(profile=profile, job=job)
    if prefer_existing:
        existing_result = await db.execute(
            select(TailoredResume)
            .where(
                TailoredResume.user_id == user_id,
                TailoredResume.job_id == job.id,
                TailoredResume.input_hash == input_hash,
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
        input_hash=input_hash,
        prompt_version=TAILORING_PROMPT_VERSION,
        rubric_version=RUBRIC_VERSION,
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
    allow_auto_reuse: bool = True,
) -> ResumeArtifact:
    job_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    artifact_result = await db.execute(
        select(ResumeArtifact).where(
            ResumeArtifact.user_id == user_id,
            ResumeArtifact.job_id == job_id,
        )
    )
    artifact = artifact_result.scalar_one_or_none()

    if (
        allow_auto_reuse
        and artifact is None
        and rewrite_decisions is None
        and await get_resume_auto_reuse_enabled(db, user_id=user_id)
    ):
        candidates = await get_resume_reuse_candidates_for_job(
            db=db,
            user_id=user_id,
            job_id=job_id,
            limit=1,
        )
        if candidates:
            reused_artifact, _ = await reuse_resume_artifact_for_job(
                db=db,
                user_id=user_id,
                job_id=job_id,
                source_artifact_id=candidates[0]["artifact"].id,
            )
            return reused_artifact

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
        prefer_existing=True,
    )
    try:
        source_evaluation = evaluate_resume_quality(
            parsed=enriched_resume,
            content=profile.resume_raw or "",
            job=job,
            rewrites=tailored.bullet_rewrites or [],
            rewrite_decisions=rewrite_decisions or {},
        )
        quality_guidance = quality_planner_guidance(source_evaluation)
    except Exception as exc:
        logger.warning("Source resume quality evaluation failed: %s", exc)
        quality_guidance = ""
    artifact_plan = await _build_resume_artifact_plan(
        parsed=enriched_resume,
        job=job,
        tailored=tailored,
        quality_guidance=quality_guidance,
    )

    filename = f"resume-{_slugify_label(job.company_name, 'company')}-{datetime.now(timezone.utc).date().isoformat()}.tex"

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
    ledger = build_truthfulness_ledger(
        parsed=enriched_resume,
        content=content,
        tailored=tailored,
        rewrite_decisions=decisions,
        auto_accept_inferred=auto_accept,
    )
    validate_truthfulness_ledger(ledger)
    render_qa = await _render_qa(content)

    artifact.tailored_resume_id = tailored.id
    artifact.reused_from_artifact_id = None
    artifact.reuse_score = None
    artifact.format = "latex"
    artifact.filename = filename
    artifact.content = content
    artifact.rewrite_decisions = decisions
    try:
        evaluation = evaluate_resume_quality(
            parsed=enriched_resume,
            content=content,
            job=job,
            rewrites=tailored.bullet_rewrites or [],
            rewrite_decisions=decisions,
        )
    except Exception as exc:
        logger.warning("Final resume quality evaluation failed: %s", exc)
        evaluation = unavailable_quality_evaluation(str(exc))
    if evaluation.get("status") == "ready":
        evaluation = _attach_render_qa(evaluation, render_qa)
    evaluation = _attach_truthfulness_ledger(evaluation, ledger)
    artifact.quality_evaluation = evaluation
    artifact.quality_score = (
        float(evaluation["overall_score"])
        if evaluation.get("status") == "ready"
        else None
    )
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
