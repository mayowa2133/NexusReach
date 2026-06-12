"""Resume artifact persistence and orchestration."""

from __future__ import annotations

import logging
import uuid
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
    _normalize_bullet_rewrites,
    tailor_resume,
)
from app.services.resume_artifact.latex import _render_resume_latex
from app.services.resume_artifact.parsed import _extract_resume_data
from app.services.resume_artifact.plan import _build_resume_artifact_plan, _job_family, score_resume_content_against_job
from app.services.resume_artifact.textnorm import _slugify_label

logger = logging.getLogger(__name__)


RESUME_REUSE_SCORE_THRESHOLD = 80.0


def _build_resume_reuse_candidate(
    *,
    artifact: ResumeArtifact,
    source_job: Job,
    target_job: Job,
    threshold: float,
) -> dict[str, Any] | None:
    source_family = _job_family(source_job)
    target_family = _job_family(target_job)
    if source_family != target_family:
        return None

    score = score_resume_content_against_job(artifact.content, target_job)
    if score is None or score < threshold:
        return None

    return {
        "artifact": artifact,
        "source_job": source_job,
        "score": score,
        "threshold": threshold,
        "job_family": target_family,
        "reason": (
            f"This saved resume scores {score:.1f}% against the new posting "
            f"and matches the {target_family.replace('_', '/')} job family."
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
    """Find existing resume artifacts that are strong enough for a target job."""
    target_result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    target_job = target_result.scalar_one_or_none()
    if not target_job:
        raise ValueError("Job not found.")

    rows = await list_resume_artifacts_for_user(db=db, user_id=user_id)
    candidates: list[dict[str, Any]] = []
    for artifact, source_job in rows:
        if artifact.job_id == job_id:
            continue
        candidate = _build_resume_reuse_candidate(
            artifact=artifact,
            source_job=source_job,
            target_job=target_job,
            threshold=threshold,
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
    """Copy a high-scoring saved resume artifact onto another job."""
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

    candidate = _build_resume_reuse_candidate(
        artifact=source_artifact,
        source_job=source_job,
        target_job=target_job,
        threshold=threshold,
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
        prefer_existing=False,
    )
    artifact_plan = await _build_resume_artifact_plan(
        parsed=enriched_resume,
        job=job,
        tailored=tailored,
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

    artifact.tailored_resume_id = tailored.id
    artifact.reused_from_artifact_id = None
    artifact.reuse_score = None
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
