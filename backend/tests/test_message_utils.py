"""Tests for message drafting utility functions — Phase 4.

Tests prompt assembly helpers from message_service.py.
"""

from unittest.mock import MagicMock

from app.services.message_service import (
    _build_user_context,
    _build_person_context,
    _build_history_context,
    CHANNEL_INSTRUCTIONS,
    GOAL_CONTEXT,
)


def _make_profile(**overrides):
    profile = MagicMock()
    profile.full_name = overrides.get("full_name", "Alice Smith")
    profile.bio = overrides.get("bio", "Aspiring software engineer")
    profile.goals = overrides.get("goals", ["Get a SWE role"])
    profile.tone = overrides.get("tone", "conversational")
    profile.target_roles = overrides.get("target_roles", ["Software Engineer"])
    profile.target_industries = overrides.get("target_industries", ["Tech"])
    profile.resume_parsed = overrides.get("resume_parsed", {
        "skills": ["Python", "React"],
        "experience": [{"title": "Intern", "company": "Startup"}],
        "projects": [{"name": "CoolApp"}],
    })
    profile.linkedin_url = overrides.get("linkedin_url", "https://linkedin.com/in/alice")
    profile.github_url = overrides.get("github_url", "https://github.com/alice")
    return profile


def _make_person(**overrides):
    person = MagicMock()
    person.full_name = overrides.get("full_name", "Bob Jones")
    person.title = overrides.get("title", "Engineering Manager")
    person.department = overrides.get("department", "Engineering")
    person.person_type = overrides.get("person_type", "hiring_manager")
    person.company = overrides.get("company", None)
    person.github_data = overrides.get("github_data", None)
    person.linkedin_url = overrides.get("linkedin_url", "https://linkedin.com/in/bob")
    person.github_url = overrides.get("github_url", None)
    return person


class TestBuildUserContext:
    def test_includes_name(self):
        ctx = _build_user_context(_make_profile())
        assert "Alice Smith" in ctx

    def test_includes_bio(self):
        ctx = _build_user_context(_make_profile())
        assert "Aspiring software engineer" in ctx

    def test_includes_skills(self):
        ctx = _build_user_context(_make_profile())
        assert "Python" in ctx

    def test_includes_recent_role(self):
        ctx = _build_user_context(_make_profile())
        assert "Intern" in ctx

    def test_no_resume_parsed(self):
        ctx = _build_user_context(_make_profile(resume_parsed=None))
        assert "Alice Smith" in ctx  # still has basic info


class TestBuildPersonContext:
    def test_includes_name_and_title(self):
        ctx = _build_person_context(_make_person())
        assert "Bob Jones" in ctx
        assert "Engineering Manager" in ctx

    def test_includes_company_info(self):
        company = MagicMock()
        company.name = "BigCo"
        company.industry = "Tech"
        company.size = "1000+"
        company.description = "Leading tech company"
        person = _make_person(company=company)
        ctx = _build_person_context(person)
        assert "BigCo" in ctx

    def test_includes_github_data(self):
        person = _make_person(github_data={"languages": ["Go", "Rust"], "repos": []})
        ctx = _build_person_context(person)
        assert "Go" in ctx


class TestBuildHistoryContext:
    def test_empty_history(self):
        assert _build_history_context([]) == ""

    def test_includes_prior_messages(self):
        from datetime import datetime
        msg = MagicMock()
        msg.created_at = datetime(2024, 1, 15)
        msg.channel = "linkedin_note"
        msg.goal = "intro"
        msg.body = "Hi, I'd love to connect!"
        ctx = _build_history_context([msg])
        assert "PREVIOUS OUTREACH" in ctx
        assert "linkedin_note" in ctx


class TestPromptConstants:
    def test_all_channels_have_instructions(self):
        expected = {"linkedin_note", "linkedin_message", "email", "follow_up", "thank_you"}
        assert set(CHANNEL_INSTRUCTIONS.keys()) == expected

    def test_all_goals_have_context(self):
        expected = {"intro", "coffee_chat", "referral", "informational", "follow_up", "thank_you"}
        assert set(GOAL_CONTEXT.keys()) == expected
