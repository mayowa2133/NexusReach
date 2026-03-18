"""Tests for People Finder utility functions — Phase 3.

Tests pure functions: _classify_person from people_service,
_split_name from email_finder_service.
"""

from app.services.people_service import (
    _candidate_matches_company,
    _classify_employment_status,
    _classify_org_level,
    _classify_person,
    _prepare_candidates,
)
from app.services.email_finder_service import _split_name
from app.utils.job_context import JobContext


class TestClassifyPerson:
    def test_recruiter(self):
        assert _classify_person("Technical Recruiter") == "recruiter"
        assert _classify_person("Talent Acquisition Specialist") == "recruiter"
        assert _classify_person("Hiring Coordinator") == "recruiter"

    def test_hiring_manager(self):
        assert _classify_person("Engineering Manager") == "hiring_manager"
        assert _classify_person("Team Lead") == "hiring_manager"
        assert _classify_person("Director of Engineering") == "hiring_manager"
        assert _classify_person("VP Engineering") == "hiring_manager"

    def test_peer(self):
        assert _classify_person("Software Engineer") == "peer"
        assert _classify_person("Frontend Developer") == "peer"
        assert _classify_person("Data Analyst") == "peer"
        assert _classify_person("Staff Software Engineer") == "peer"
        assert _classify_person("Principal Engineer") == "peer"

    def test_empty_title(self):
        assert _classify_person("") == "peer"
        assert _classify_person(None) == "peer"


class TestSplitName:
    def test_two_parts(self):
        first, last = _split_name("John Doe")
        assert first == "John"
        assert last == "Doe"

    def test_three_parts(self):
        first, last = _split_name("John Michael Doe")
        assert first == "John"
        assert last == "Michael Doe"

    def test_single_name(self):
        first, last = _split_name("Madonna")
        assert first == "Madonna"
        assert last == ""

    def test_empty_string(self):
        first, last = _split_name("")
        assert first == ""
        assert last == ""

    def test_none(self):
        first, last = _split_name(None)
        assert first == ""
        assert last == ""


class TestEmploymentAndRanking:
    def test_classify_employment_status_former(self):
        status = _classify_employment_status(
            {
                "title": "Former Engineering Manager",
                "snippet": "Former engineering manager at Two Sigma",
                "source": "brave_search",
            },
            "Two Sigma",
        )

        assert status == "former"

    def test_candidate_matches_company_rejects_other_org_chart(self):
        assert _candidate_matches_company(
            {
                "title": "Technical Recruiter",
                "snippet": "Worked in engineering talent acquisition at Two Sigma.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://theorg.com/org/jane-street-capital/org-chart/someone"
                },
            },
            "Two Sigma",
        ) is False

    def test_classify_org_level(self):
        assert _classify_org_level("Software Engineer") == "ic"
        assert _classify_org_level("Engineering Manager") == "manager"
        assert _classify_org_level("Managing Director") == "director_plus"

    def test_prepare_candidates_prefers_current_manager_before_director_fallback(self):
        context = JobContext(
            department="engineering",
            team_keywords=["backend"],
            domain_keywords=[],
            seniority="mid",
        )
        candidates = [
            {
                "full_name": "Director Dana",
                "title": "Director of Engineering",
                "snippet": "Currently at Two Sigma",
                "source": "brave_search",
            },
            {
                "full_name": "Manager Morgan",
                "title": "Engineering Manager",
                "snippet": "Currently at Two Sigma",
                "source": "brave_search",
            },
            {
                "full_name": "Ambiguous Avery",
                "title": "Engineering Manager",
                "snippet": "Worked on backend systems at Two Sigma",
                "source": "brave_search",
            },
        ]

        results = _prepare_candidates(
            candidates,
            company_name="Two Sigma",
            bucket="hiring_managers",
            context=context,
            limit=3,
        )

        assert [candidate["full_name"] for candidate in results] == [
            "Manager Morgan",
            "Ambiguous Avery",
            "Director Dana",
        ]
