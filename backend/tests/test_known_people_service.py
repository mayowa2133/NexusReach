"""Tests for the global known people cache service."""

from app.services.known_people_service import (
    GLOBAL_CACHE_BLOCKED_SOURCES,
    GLOBAL_CACHE_ELIGIBLE_SOURCES,
    _normalize_name,
    is_cache_eligible,
)


# ---------------------------------------------------------------------------
# Source eligibility
# ---------------------------------------------------------------------------


def test_eligible_public_sources_allowed():
    for source in GLOBAL_CACHE_ELIGIBLE_SOURCES:
        candidate = {"source": source, "full_name": "Test"}
        assert is_cache_eligible(candidate), f"{source} should be eligible"


def test_blocked_sources_rejected():
    for source in GLOBAL_CACHE_BLOCKED_SOURCES:
        candidate = {"source": source, "full_name": "Test"}
        assert not is_cache_eligible(candidate), f"{source} should be blocked"


def test_unknown_source_rejected():
    candidate = {"source": "totally_new_source", "full_name": "Test"}
    assert not is_cache_eligible(candidate)


def test_empty_source_rejected():
    assert not is_cache_eligible({"source": "", "full_name": "Test"})
    assert not is_cache_eligible({"full_name": "Test"})


def test_linkedin_import_sources_never_eligible():
    """Critical privacy boundary: user-imported LinkedIn data must never enter the cache."""
    assert not is_cache_eligible({"source": "local_sync", "full_name": "Test"})
    assert not is_cache_eligible({"source": "manual_import", "full_name": "Test"})
    assert not is_cache_eligible({"source": "manual", "full_name": "Test"})


def test_source_matching_is_case_insensitive():
    assert is_cache_eligible({"source": "Apollo", "full_name": "Test"})
    assert is_cache_eligible({"source": " apollo ", "full_name": "Test"})


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------


def test_normalize_name_basic():
    assert _normalize_name("John Doe") == "john doe"
    assert _normalize_name("  JANE   DOE  ") == "jane doe"
    assert _normalize_name("María García") == "maría garcía"


def test_normalize_name_collapses_whitespace():
    assert _normalize_name("John\t\n  Doe") == "john doe"


def test_normalize_name_empty():
    assert _normalize_name("") == ""
    assert _normalize_name("   ") == ""
