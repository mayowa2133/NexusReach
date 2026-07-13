from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.resume_artifact.service import (
    generate_resume_artifact_for_job,
    reuse_resume_artifact_for_job,
    tailoring_input_hash,
)


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _ready_evaluation(score: float) -> dict:
    return {
        "status": "ready",
        "overall_score": score,
        "axes": {"evidence_quality": {"score": score}},
        "profile": "early_career_technical_v1",
        "improvements": [],
    }


_RENDER_QA = {
    "status": "passed",
    "page_count": 1,
    "parser_agreement": 1.0,
}


def test_tailoring_input_hash_is_stable_and_changes_with_inputs():
    profile = SimpleNamespace(
        resume_parsed={"skills": ["Python"]},
        resume_raw="ignored when parsed exists",
    )
    job = SimpleNamespace(
        title="Software Engineer",
        company_name="Acme",
        description="Build Python services.",
        experience_level="mid",
        tags=["occupation:software_engineering"],
    )

    first = tailoring_input_hash(profile=profile, job=job)
    second = tailoring_input_hash(profile=profile, job=job)
    changed_profile = SimpleNamespace(
        resume_parsed={"skills": ["Python", "SQL"]},
        resume_raw="",
    )

    assert first == second
    assert len(first) == 64
    assert tailoring_input_hash(profile=changed_profile, job=job) != first
    assert tailoring_input_hash(
        profile=profile,
        job=SimpleNamespace(**{**job.__dict__, "description": "Build Go services."}),
    ) != first


@pytest.mark.asyncio
async def test_generation_uses_source_guidance_and_persists_final_artifact_evaluation():
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        user_id=user_id,
        title="Software Engineer Intern",
        company_name="Acme",
        description="Build Python services.",
        remote=False,
        experience_level="intern",
        tags=["occupation:software_engineering"],
        department="engineering",
    )
    artifact = SimpleNamespace(
        id=uuid.uuid4(),
        rewrite_decisions={},
    )
    parsed = {
        "experience": [{"company": "Example", "title": "Intern", "bullets": ["Built APIs."]}],
        "skills": ["Python"],
    }
    profile = SimpleNamespace(
        resume_parsed=parsed,
        resume_raw="candidate@example.com Built APIs with Python.",
        resume_auto_accept_inferred=False,
    )
    user = SimpleNamespace(id=user_id, email="candidate@example.com")
    tailored = SimpleNamespace(
        id=uuid.uuid4(),
        bullet_rewrites=[],
        skills_to_emphasize=["Python"],
        skills_to_add=[],
        keywords_to_add=[],
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _scalar_result(job),
                _scalar_result(artifact),
                _scalar_result(profile),
                _scalar_result(user),
            ]
        ),
        add=MagicMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    source_evaluation = _ready_evaluation(52.0)
    final_evaluation = _ready_evaluation(84.0)

    with patch(
        "app.services.resume_artifact.service._extract_resume_data",
        return_value=parsed,
    ), patch(
        "app.services.resume_artifact.service._load_or_generate_tailoring",
        new_callable=AsyncMock,
        return_value=tailored,
    ) as load_tailoring, patch(
        "app.services.resume_artifact.service.evaluate_resume_quality",
        side_effect=[source_evaluation, final_evaluation],
    ) as evaluate, patch(
        "app.services.resume_artifact.service.quality_planner_guidance",
        return_value='{"priorities":["keep measurable evidence"]}',
    ), patch(
        "app.services.resume_artifact.service._build_resume_artifact_plan",
        new_callable=AsyncMock,
        return_value={"experience": [], "projects": []},
    ) as build_plan, patch(
        "app.services.resume_artifact.service._render_resume_latex",
        return_value="FINAL_RENDERED_LATEX",
    ), patch(
        "app.services.resume_artifact.service._render_qa",
        new_callable=AsyncMock,
        return_value=_RENDER_QA,
    ):
        result = await generate_resume_artifact_for_job(
            db,
            user_id=user_id,
            job_id=job_id,
            allow_auto_reuse=False,
        )

    assert result is artifact
    assert artifact.content == "FINAL_RENDERED_LATEX"
    assert artifact.quality_score == 84.0
    assert artifact.quality_evaluation["render_qa"] == _RENDER_QA
    assert build_plan.await_args.kwargs["quality_guidance"] == (
        '{"priorities":["keep measurable evidence"]}'
    )
    assert evaluate.call_count == 2
    assert load_tailoring.await_args.kwargs["prefer_existing"] is True
    assert evaluate.call_args_list[1].kwargs["content"] == "FINAL_RENDERED_LATEX"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_generation_fails_soft_when_quality_evaluation_errors():
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        user_id=user_id,
        title="Analyst",
        company_name="Acme",
        description="Analyze operations.",
        remote=False,
        experience_level=None,
        tags=["occupation:business_analyst"],
        department="operations",
    )
    artifact = SimpleNamespace(id=uuid.uuid4(), rewrite_decisions={})
    profile = SimpleNamespace(
        resume_parsed={"skills": ["Analysis"]},
        resume_raw="Analysis",
        resume_auto_accept_inferred=False,
    )
    tailored = SimpleNamespace(
        id=uuid.uuid4(),
        bullet_rewrites=[],
        skills_to_emphasize=[],
        skills_to_add=[],
        keywords_to_add=[],
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _scalar_result(job),
                _scalar_result(artifact),
                _scalar_result(profile),
                _scalar_result(SimpleNamespace(email="candidate@example.com")),
            ]
        ),
        add=MagicMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )

    with patch(
        "app.services.resume_artifact.service._extract_resume_data",
        return_value=profile.resume_parsed,
    ), patch(
        "app.services.resume_artifact.service._load_or_generate_tailoring",
        new_callable=AsyncMock,
        return_value=tailored,
    ), patch(
        "app.services.resume_artifact.service.evaluate_resume_quality",
        side_effect=RuntimeError("evaluation boom"),
    ), patch(
        "app.services.resume_artifact.service._build_resume_artifact_plan",
        new_callable=AsyncMock,
        return_value={"experience": [], "projects": []},
    ), patch(
        "app.services.resume_artifact.service._render_resume_latex",
        return_value="VALID_ARTIFACT",
    ), patch(
        "app.services.resume_artifact.service._render_qa",
        new_callable=AsyncMock,
        return_value=_RENDER_QA,
    ):
        result = await generate_resume_artifact_for_job(
            db,
            user_id=user_id,
            job_id=job_id,
            allow_auto_reuse=False,
        )

    assert result.content == "VALID_ARTIFACT"
    assert result.quality_score is None
    assert result.quality_evaluation["status"] == "unavailable"
    assert "evaluation boom" in result.quality_evaluation["reason"]


@pytest.mark.asyncio
async def test_reuse_recomputes_quality_for_target_job_instead_of_copying_stale_score():
    user_id = uuid.uuid4()
    target_job = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        title="Frontend Engineer",
        company_name="Target",
        description="Build React interfaces.",
        tags=["occupation:software_engineering"],
        department="engineering",
    )
    source_job = SimpleNamespace(
        id=uuid.uuid4(),
        title="Backend Engineer",
        company_name="Source",
        description="Build Python services.",
    )
    source_artifact = SimpleNamespace(
        id=uuid.uuid4(),
        job_id=source_job.id,
        format="latex",
        content="SOURCE_LATEX",
        quality_score=96.0,
        quality_evaluation={"status": "ready", "overall_score": 96.0},
    )
    target_artifact = SimpleNamespace(id=uuid.uuid4())
    source_result = MagicMock()
    source_result.one_or_none.return_value = (source_artifact, source_job)
    profile = SimpleNamespace(resume_parsed={"skills": ["React"]})
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _scalar_result(target_job),
                source_result,
                _scalar_result(profile),
                _scalar_result(target_artifact),
            ]
        ),
        add=MagicMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    candidate = {
        "score": 88.0,
        "artifact": source_artifact,
        "source_job": source_job,
    }
    target_evaluation = _ready_evaluation(72.0)

    with patch(
        "app.services.resume_artifact.service._build_resume_reuse_candidate",
        return_value=candidate,
    ), patch(
        "app.services.resume_artifact.service.evaluate_resume_quality",
        return_value=target_evaluation,
    ) as evaluate, patch(
        "app.services.resume_artifact.service._render_qa",
        new_callable=AsyncMock,
        return_value=_RENDER_QA,
    ):
        result, returned_source = await reuse_resume_artifact_for_job(
            db,
            user_id=user_id,
            job_id=target_job.id,
            source_artifact_id=source_artifact.id,
        )

    assert returned_source is source_job
    assert result.content == "SOURCE_LATEX"
    assert result.quality_score == 72.0
    assert result.quality_evaluation["render_qa"] == _RENDER_QA
    assert evaluate.call_args.kwargs["job"] is target_job
