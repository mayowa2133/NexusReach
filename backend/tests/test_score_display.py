import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.match_scoring import deep_analyze_match
from app.services.score_display import (
    public_match_score,
    public_resume_quality_evaluation,
)


def test_internal_job_score_is_withheld_from_public_contract():
    score, calibration = public_match_score(87.5)

    assert score is None
    assert calibration["score_kind"] == "job_match"
    assert calibration["calibrated"] is False
    assert calibration["display_mode"] == "dimensions_only"


def test_resume_aggregate_is_withheld_but_dimensions_are_preserved():
    source = {
        "status": "ready",
        "overall_score": 91.0,
        "readiness": "strong",
        "axes": {"job_fit": {"score": 82, "max": 100}},
    }

    public = public_resume_quality_evaluation(source)

    assert public is not None
    assert public["overall_score"] is None
    assert public["readiness"] is None
    assert public["axes"] == source["axes"]
    assert public["calibration"]["score_kind"] == "resume_readiness"
    assert public["calibration"]["calibrated"] is False
    # Sanitization must not mutate the persisted internal evaluation.
    assert source["overall_score"] == 91.0
    assert source["readiness"] == "strong"


@pytest.mark.asyncio
async def test_match_analysis_prompt_cannot_repeat_internal_aggregate():
    profile = MagicMock()
    profile.target_roles = ["Data Analyst"]
    profile.resume_parsed = {
        "skills": ["SQL"],
        "experience": [],
        "education": [],
    }
    generate = AsyncMock(return_value={
        "draft": json.dumps({
            "summary": "SQL evidence aligns with one requirement.",
            "strengths": ["SQL"],
            "gaps": [],
            "recommendations": [],
        }),
        "model": "test",
        "usage": {},
    })

    with patch("app.clients.llm_client.generate_message", generate):
        await deep_analyze_match(
            {"title": "Data Analyst", "description": "Requires SQL"},
            profile,
            87.5,
            {"skills_match": 30, "category_maxes": {"skills_match": 35}},
        )

    system_prompt = generate.call_args.kwargs["system_prompt"]
    user_prompt = generate.call_args.kwargs["user_prompt"]
    assert "87.5" not in user_prompt
    assert "match score" not in user_prompt.lower()
    assert "not an outcome prediction" in user_prompt
    assert "do not state or infer an aggregate match percentage" in system_prompt.lower()
