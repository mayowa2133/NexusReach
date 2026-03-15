"""Tests for People Finder utility functions — Phase 3.

Tests pure functions: _classify_person from people_service,
_split_name from email_finder_service.
"""

from app.services.people_service import _classify_person
from app.services.email_finder_service import _split_name


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
