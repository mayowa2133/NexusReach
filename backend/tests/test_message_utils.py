"""Tests for message drafting utility functions — Phase 4.

Tests prompt assembly helpers from message_service.py.
"""

from unittest.mock import MagicMock

from app.services.message_service import (
    _build_user_context,
    _build_person_context,
    _build_history_context,
    _build_job_context,
    _build_warm_path_context,
    _normalize_goal,
    _resolve_cta_plan,
    CHANNEL_INSTRUCTIONS,
    GOAL_CONTEXT,
)


def test_build_warm_path_context_none_returns_empty():
    assert _build_warm_path_context(None) == ""
    assert _build_warm_path_context({}) == ""
    assert _build_warm_path_context({"type": "mystery"}) == ""


def test_build_warm_path_context_direct_connection_mentions_existing_tie():
    out = _build_warm_path_context(
        {
            "type": "direct_connection",
            "connection_name": "Jane Doe",
            "connection_headline": "Recruiter",
            "connection_linkedin_url": "https://www.linkedin.com/in/jane-doe",
        }
    )
    assert "WARM PATH" in out
    assert "1st-degree LinkedIn connection with the recipient" in out
    assert "Jane Doe" in out
    assert "do NOT fabricate" in out


def test_build_warm_path_context_bridge_warns_against_implying_intro():
    out = _build_warm_path_context(
        {
            "type": "same_company_bridge",
            "connection_name": "Maria Chan",
            "connection_headline": "Senior Recruiter",
            "connection_linkedin_url": None,
        }
    )
    assert "same company" in out
    assert "Maria Chan (Senior Recruiter)" in out
    assert "Do not ask the recipient to vouch" in out


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
        expected = {"interview", "referral", "warm_intro", "follow_up", "thank_you"}
        assert set(GOAL_CONTEXT.keys()) == expected


class TestGoalNormalization:
    def test_maps_intro_to_warm_intro(self):
        assert _normalize_goal("intro") == "warm_intro"

    def test_maps_coffee_chat_to_warm_intro(self):
        assert _normalize_goal("coffee_chat") == "warm_intro"

    def test_keeps_interview_goal(self):
        assert _normalize_goal("interview") == "interview"


class TestCTAResolution:
    def test_peer_interview_uses_redirect_then_referral(self):
        assert _resolve_cta_plan("peer", "interview", []) == ("redirect", "referral")

    def test_recruiter_interview_uses_interview_then_redirect(self):
        assert _resolve_cta_plan("recruiter", "interview", []) == ("interview", "redirect")


class TestBuildJobContext:
    def test_includes_job_title_company_and_keywords(self):
        job = MagicMock()
        job.id = "job-1"
        job.title = "Software Engineer, Backend (Marketplace Performance)"
        job.company_name = "Affirm"
        job.location = "Remote"
        job.remote = True
        job.department = "Engineering"
        job.description = (
            "Build backend systems for search, discovery, and marketplace experiences. "
            "Work with merchants and consumer teams."
        )

        text, snapshot = _build_job_context(job)

        assert "Software Engineer, Backend" in text
        assert "Affirm" in text
        assert snapshot is not None
        assert snapshot["company_name"] == "Affirm"
        assert "marketplace" in snapshot["domain_keywords"]
