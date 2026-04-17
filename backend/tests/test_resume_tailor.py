"""Tests for the resume tailoring service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.resume_tailor import (
    tailor_resume,
    _build_resume_context,
    _build_job_context,
)


def _make_profile(**overrides):
    p = MagicMock()
    p.resume_parsed = overrides.get("resume_parsed", {
        "skills": ["Python", "FastAPI", "PostgreSQL", "React"],
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Software Engineer",
                "start_date": "2023-01",
                "end_date": None,
                "description": "Built REST APIs and managed databases",
            },
            {
                "company": "StartupCo",
                "title": "Junior Developer",
                "start_date": "2021-06",
                "end_date": "2022-12",
                "description": "Developed frontend features using React",
            },
        ],
        "education": [
            {
                "institution": "State University",
                "degree": "B.S.",
                "field": "Computer Science",
                "graduation_date": "2021",
            },
        ],
        "projects": [
            {
                "name": "TaskManager",
                "description": "A task management app",
                "technologies": ["React", "Node.js"],
                "url": "https://github.com/user/taskmanager",
            },
        ],
    })
    p.target_roles = overrides.get("target_roles", ["Backend Engineer"])
    p.target_locations = overrides.get("target_locations", ["San Francisco"])
    return p


def _make_job(**overrides):
    return {
        "title": overrides.get("title", "Senior Backend Engineer"),
        "company_name": overrides.get("company_name", "TechCorp"),
        "location": overrides.get("location", "San Francisco, CA"),
        "description": overrides.get("description", (
            "We are looking for a Senior Backend Engineer with experience in "
            "Python, Django, and PostgreSQL. Must have 3+ years of experience "
            "building scalable microservices. Knowledge of Kubernetes, Docker, "
            "and CI/CD pipelines is required."
        )),
        "remote": overrides.get("remote", False),
        "experience_level": overrides.get("experience_level", "senior"),
    }


class TestBuildResumeContext:
    def test_includes_skills(self):
        profile = _make_profile()
        ctx = _build_resume_context(profile)
        assert "Python" in ctx
        assert "FastAPI" in ctx

    def test_includes_experience(self):
        profile = _make_profile()
        ctx = _build_resume_context(profile)
        assert "Software Engineer" in ctx
        assert "Acme Corp" in ctx
        assert "[0]" in ctx  # index marker

    def test_includes_education(self):
        profile = _make_profile()
        ctx = _build_resume_context(profile)
        assert "Computer Science" in ctx
        assert "State University" in ctx

    def test_includes_projects(self):
        profile = _make_profile()
        ctx = _build_resume_context(profile)
        assert "TaskManager" in ctx

    def test_includes_target_roles(self):
        profile = _make_profile()
        ctx = _build_resume_context(profile)
        assert "Backend Engineer" in ctx

    def test_empty_resume_still_has_targets(self):
        profile = _make_profile(resume_parsed={})
        ctx = _build_resume_context(profile)
        # No skills/experience, but target roles still present
        assert "SKILLS" not in ctx
        assert "EXPERIENCE" not in ctx
        assert "Backend Engineer" in ctx

    def test_truly_empty_resume_and_targets(self):
        profile = _make_profile(
            resume_parsed={}, target_roles=None, target_locations=None
        )
        ctx = _build_resume_context(profile)
        assert ctx == "(no resume data)"


class TestBuildJobContext:
    def test_includes_title_and_company(self):
        job = _make_job()
        ctx = _build_job_context(job)
        assert "Senior Backend Engineer" in ctx
        assert "TechCorp" in ctx

    def test_includes_description(self):
        job = _make_job()
        ctx = _build_job_context(job)
        assert "Python" in ctx
        assert "microservices" in ctx

    def test_truncates_long_description(self):
        job = _make_job(description="x" * 7000)
        ctx = _build_job_context(job)
        assert "[...truncated]" in ctx

    def test_includes_remote(self):
        job = _make_job(remote=True)
        ctx = _build_job_context(job)
        assert "REMOTE: Yes" in ctx


class TestTailorResume:
    @pytest.mark.asyncio
    async def test_returns_structured_result(self):
        fake_response = {
            "summary": "Focus on backend and infrastructure skills",
            "skills_to_emphasize": ["Python", "PostgreSQL"],
            "skills_to_add": ["Django", "Kubernetes"],
            "keywords_to_add": ["microservices", "CI/CD"],
            "bullet_rewrites": [
                {
                    "original": "Built REST APIs",
                    "rewritten": "Designed and built scalable REST APIs serving 10k+ requests/day",
                    "reason": "Quantify impact",
                    "experience_index": 0,
                },
            ],
            "section_suggestions": [
                {"section": "summary", "suggestion": "Add a summary emphasizing backend expertise"},
            ],
            "overall_strategy": "Reframe as a backend-focused engineer",
        }

        mock_llm = AsyncMock(return_value={
            "draft": json.dumps(fake_response),
            "reasoning": "",
            "model": "claude-sonnet-4-20250514",
            "provider": "anthropic",
            "usage": {"input_tokens": 100, "output_tokens": 200},
        })

        with patch("app.services.resume_tailor.generate_message", mock_llm):
            result = await tailor_resume(_make_job(), _make_profile())

        assert result["summary"] == "Focus on backend and infrastructure skills"
        assert "Python" in result["skills_to_emphasize"]
        assert "Django" in result["skills_to_add"]
        assert len(result["bullet_rewrites"]) == 1
        assert result["bullet_rewrites"][0]["experience_index"] == 0
        assert result["model"] == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_handles_markdown_fenced_json(self):
        fake_json = json.dumps({
            "summary": "Test",
            "skills_to_emphasize": [],
            "skills_to_add": [],
            "keywords_to_add": [],
            "bullet_rewrites": [],
            "section_suggestions": [],
            "overall_strategy": "Test strategy",
        })
        fenced = f"```json\n{fake_json}\n```"

        mock_llm = AsyncMock(return_value={
            "draft": fenced,
            "reasoning": "",
            "model": "test-model",
            "provider": "test",
            "usage": {"input_tokens": 50, "output_tokens": 100},
        })

        with patch("app.services.resume_tailor.generate_message", mock_llm):
            result = await tailor_resume(_make_job(), _make_profile())

        assert result["summary"] == "Test"
        assert result["overall_strategy"] == "Test strategy"

    @pytest.mark.asyncio
    async def test_handles_invalid_json_gracefully(self):
        mock_llm = AsyncMock(return_value={
            "draft": "This is not valid JSON at all",
            "reasoning": "",
            "model": "test-model",
            "provider": "test",
            "usage": {"input_tokens": 50, "output_tokens": 100},
        })

        with patch("app.services.resume_tailor.generate_message", mock_llm):
            result = await tailor_resume(_make_job(), _make_profile())

        # Should gracefully degrade
        assert result["summary"] != ""
        assert isinstance(result["skills_to_emphasize"], list)
        assert isinstance(result["bullet_rewrites"], list)

    @pytest.mark.asyncio
    async def test_includes_score_context_in_prompt(self):
        mock_llm = AsyncMock(return_value={
            "draft": json.dumps({
                "summary": "s", "skills_to_emphasize": [],
                "skills_to_add": [], "keywords_to_add": [],
                "bullet_rewrites": [], "section_suggestions": [],
                "overall_strategy": "o",
            }),
            "reasoning": "", "model": "m", "provider": "p",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })

        with patch("app.services.resume_tailor.generate_message", mock_llm):
            await tailor_resume(
                _make_job(), _make_profile(),
                score=72.5,
                breakdown={
                    "skills_match": 28.0,
                    "role_match": 15.0,
                    "category_maxes": {"skills_match": 35, "role_match": 20},
                    "skills_detail": {"matched": ["Python", "PostgreSQL"]},
                },
            )

        # Check that score context was included in the user prompt
        call_args = mock_llm.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args[0][1]
        assert "72/100" in user_prompt or "73/100" in user_prompt
        assert "skills_match" in user_prompt
        assert "Python" in user_prompt
