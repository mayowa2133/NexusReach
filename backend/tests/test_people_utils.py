"""Tests for People Finder utility functions — Phase 3.

Tests pure functions: _classify_person from people_service,
_split_name from email_finder_service.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.people_service import (
    _candidate_matches_company,
    _classify_employment_status,
    _classify_org_level,
    _classify_person,
    _prepare_candidates,
    get_or_create_company,
)
from app.services.email_finder_service import _split_name
from app.utils.job_context import JobContext


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        value = self._value

        class _Scalars:
            def __init__(self, raw):
                self._raw = raw

            def first(self):
                if isinstance(self._raw, list):
                    return self._raw[0] if self._raw else None
                return self._raw

        return _Scalars(value)


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
    @pytest.mark.asyncio
    async def test_get_or_create_company_reuses_normalized_company_name(self):
        existing = SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Zip",
            normalized_name="zip",
            domain=None,
            domain_trusted=False,
            public_identity_slugs=[],
            identity_hints={},
            email_pattern=None,
            email_pattern_confidence=None,
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=_ScalarResult(existing))

        with patch(
            "app.services.people_service.apollo_client.search_company",
            new_callable=AsyncMock,
            return_value={"name": "Zip Co", "domain": "zip.co"},
        ):
            company = await get_or_create_company(db, existing.user_id, "zip")

        assert company is existing
        assert company.name == "Zip"
        assert company.domain is None
        assert company.domain_trusted is False
        assert "zip" in company.public_identity_slugs
        assert "ziphq" in company.public_identity_slugs

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

    def test_candidate_matches_company_rejects_ziprecruiter_for_zip(self):
        assert _candidate_matches_company(
            {
                "title": "Technical Recruiter",
                "snippet": "Technical recruiter at ZipRecruiter focused on engineering hiring.",
                "source": "brave_search",
            },
            "Zip",
        ) is False

    def test_candidate_matches_company_accepts_theorg_slug_for_ambiguous_company(self):
        assert _candidate_matches_company(
            {
                "title": "Andre Nguyen - Sr Technical Recruiter",
                "snippet": "Currently serving as a Sr Technical Recruiter at Zip.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://theorg.com/org/ziphq/org-chart/andre-nguyen",
                    "public_identity_slug": "ziphq",
                },
            },
            "Zip",
            ["zip", "ziphq"],
        ) is True

    def test_candidate_matches_company_rejects_directory_style_public_result(self):
        assert _candidate_matches_company(
            {
                "title": "Courtney Cronin's Email & Phone",
                "snippet": "Staff directory and contact information for Zip.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://www.contactout.com/courtney-cronin",
                },
            },
            "Zip",
            ["zip", "ziphq"],
        ) is False

    def test_classify_employment_status_marks_theorg_slug_match_current(self):
        status = _classify_employment_status(
            {
                "title": "Sophia Feng - Software Engineer",
                "snippet": "Software Engineer, Payments at Zip.",
                "source": "brave_public_web",
                "profile_data": {
                    "public_url": "https://theorg.com/org/ziphq/org-chart/sophia-feng",
                    "public_identity_slug": "ziphq",
                },
            },
            "Zip",
            ["zip", "ziphq"],
        )

        assert status == "current"

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
