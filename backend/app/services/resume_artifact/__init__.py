"""Resume artifact package: plan, render, redline, and persist LaTeX resumes.

Module layering (each module imports only from those below it):

    service            persistence + orchestration
    redline            redline diff PDF generation
    latex              LaTeX rendering and PDF generation
    plan               artifact plan, layout, relevance scoring
    parsed, rewrites   parsed-resume repair, rewrite decisions
    textnorm           bullet/text primitives
"""

from app.services.resume_artifact.latex import (
    render_resume_artifact_pdf,
    render_resume_artifact_pdf_async,
)
from app.services.resume_artifact.plan import score_resume_content_against_job
from app.services.resume_artifact.redline import (
    render_resume_artifact_redline_pdf,
    render_resume_artifact_redline_pdf_async,
)
from app.services.resume_artifact.quality import (
    evaluate_resume_quality,
    quality_planner_guidance,
    select_quality_profile,
    validate_quality_evaluation,
)
from app.services.resume_artifact.service import (
    RESUME_REUSE_QUALITY_THRESHOLD,
    RESUME_REUSE_SCORE_THRESHOLD,
    generate_resume_artifact_for_job,
    get_resume_artifact_for_job,
    get_resume_auto_reuse_enabled,
    get_resume_reuse_candidates_for_job,
    list_resume_artifacts_for_user,
    reuse_resume_artifact_for_job,
)

__all__ = [
    "RESUME_REUSE_SCORE_THRESHOLD",
    "RESUME_REUSE_QUALITY_THRESHOLD",
    "evaluate_resume_quality",
    "generate_resume_artifact_for_job",
    "get_resume_artifact_for_job",
    "get_resume_auto_reuse_enabled",
    "get_resume_reuse_candidates_for_job",
    "list_resume_artifacts_for_user",
    "render_resume_artifact_pdf",
    "render_resume_artifact_pdf_async",
    "render_resume_artifact_redline_pdf",
    "render_resume_artifact_redline_pdf_async",
    "quality_planner_guidance",
    "reuse_resume_artifact_for_job",
    "select_quality_profile",
    "score_resume_content_against_job",
    "validate_quality_evaluation",
]
