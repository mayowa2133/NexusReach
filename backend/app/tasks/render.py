"""Credential-free LaTeX rendering tasks routed to the isolated render queue."""

from __future__ import annotations

from typing import Any

from app.tasks import celery_app


@celery_app.task(
    name="app.tasks.render.render_pdf",
    soft_time_limit=25,
    time_limit=30,
    acks_late=True,
)
def render_pdf(content: str) -> bytes:
    from app.services.resume_artifact.latex import render_resume_artifact_pdf

    return render_resume_artifact_pdf(content)


@celery_app.task(
    name="app.tasks.render.render_redline_pdf",
    soft_time_limit=25,
    time_limit=30,
    acks_late=True,
)
def render_redline_pdf(
    content: str,
    rewrites: list[dict[str, Any]] | None,
    decisions: dict[str, str] | None,
    auto_accept_inferred: bool = False,
) -> bytes:
    from app.services.resume_artifact.redline import render_resume_artifact_redline_pdf

    return render_resume_artifact_redline_pdf(
        content,
        rewrites,
        decisions,
        auto_accept_inferred=auto_accept_inferred,
    )
