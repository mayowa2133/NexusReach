"""Tests for email_suggestion_client — pattern suggestion with confidence scores."""

import pytest

from app.clients.email_suggestion_client import (
    KNOWN_COMPANY_PATTERNS,
    DEFAULT_CONFIDENCE,
    _apply_format,
    _normalize,
    _generate_ranked_suggestions,
    suggest_email,
)


# --------------------------------------------------------------------------- #
# _normalize
# --------------------------------------------------------------------------- #
class TestNormalize:
    def test_basic_lowercase(self) -> None:
        assert _normalize("John") == "john"

    def test_accent_stripping(self) -> None:
        assert _normalize("José") == "jose"

    def test_non_alpha_removed(self) -> None:
        assert _normalize("O'Brien") == "obrien"

    def test_hyphenated_name(self) -> None:
        assert _normalize("Smith-Jones") == "smithjones"

    def test_empty(self) -> None:
        assert _normalize("") == ""


# --------------------------------------------------------------------------- #
# _apply_format
# --------------------------------------------------------------------------- #
class TestApplyFormat:
    def test_first_dot_last(self) -> None:
        assert _apply_format("first.last", "john", "doe", "amazon.com") == "john.doe@amazon.com"

    def test_firstlast(self) -> None:
        assert _apply_format("firstlast", "john", "doe", "meta.com") == "johndoe@meta.com"

    def test_flast(self) -> None:
        assert _apply_format("flast", "john", "doe", "example.com") == "jdoe@example.com"

    def test_first_only(self) -> None:
        assert _apply_format("first", "john", "doe", "google.com") == "john@google.com"

    def test_firstl(self) -> None:
        assert _apply_format("firstl", "john", "doe", "example.com") == "johnd@example.com"

    def test_first_underscore_last(self) -> None:
        assert _apply_format("first_last", "john", "doe", "apple.com") == "john_doe@apple.com"

    def test_last_dot_first(self) -> None:
        assert _apply_format("last.first", "john", "doe", "example.com") == "doe.john@example.com"

    def test_unknown_format_returns_none(self) -> None:
        assert _apply_format("unknown", "john", "doe", "example.com") is None

    def test_no_first_name_returns_none(self) -> None:
        assert _apply_format("first.last", "", "doe", "example.com") is None

    def test_no_last_name_first_dot_last_returns_none(self) -> None:
        assert _apply_format("first.last", "john", "", "example.com") is None

    def test_first_format_works_without_last(self) -> None:
        assert _apply_format("first", "john", "", "google.com") == "john@google.com"


# --------------------------------------------------------------------------- #
# _generate_ranked_suggestions
# --------------------------------------------------------------------------- #
class TestGenerateRankedSuggestions:
    def test_known_pattern_is_primary(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "amazon.com", "first.last", 90
        )
        assert suggestions[0]["email"] == "john.doe@amazon.com"
        assert suggestions[0]["confidence"] == 90

    def test_alternates_have_lower_confidence(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "amazon.com", "first.last", 90
        )
        # All alternates should have confidence = max(90 - 20, 15) = 70
        for s in suggestions[1:]:
            assert s["confidence"] == 70

    def test_primary_not_duplicated_in_alternates(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "amazon.com", "first.last", 90
        )
        emails = [s["email"] for s in suggestions]
        # first.last should appear only once (as primary)
        assert emails.count("john.doe@amazon.com") == 1

    def test_google_format_first_is_primary(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "google.com", "first", 85
        )
        assert suggestions[0]["email"] == "john@google.com"
        assert suggestions[0]["confidence"] == 85

    def test_meta_format_firstlast_is_primary(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "meta.com", "firstlast", 80
        )
        assert suggestions[0]["email"] == "johndoe@meta.com"
        assert suggestions[0]["confidence"] == 80

    def test_unknown_domain_defaults_to_first_dot_last(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "unknown.com", None, 40
        )
        # None means use DEFAULT_PATTERN which is "first.last"
        assert suggestions[0]["email"] == "john.doe@unknown.com"
        assert suggestions[0]["confidence"] == 40

    def test_low_confidence_alternates_have_floor_of_15(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "unknown.com", None, 25
        )
        for s in suggestions[1:]:
            assert s["confidence"] == 15

    def test_generates_multiple_suggestions(self) -> None:
        suggestions = _generate_ranked_suggestions(
            "john", "doe", "amazon.com", "first.last", 90
        )
        # Should have primary + several alternates
        assert len(suggestions) >= 4


# --------------------------------------------------------------------------- #
# suggest_email — main function
# --------------------------------------------------------------------------- #
class TestSuggestEmail:
    def test_known_company_amazon(self) -> None:
        result = suggest_email("John", "Doe", "amazon.com")
        assert result is not None
        assert result["email"] == "john.doe@amazon.com"
        assert result["confidence"] == 90
        assert result["source"] == "pattern_suggestion"
        assert result["verified"] is False
        assert result["known_company"] is True

    def test_known_company_google(self) -> None:
        result = suggest_email("Jane", "Smith", "google.com")
        assert result is not None
        assert result["email"] == "jane@google.com"
        assert result["confidence"] == 85
        assert result["known_company"] is True

    def test_known_company_meta(self) -> None:
        result = suggest_email("Bob", "Wilson", "meta.com")
        assert result is not None
        assert result["email"] == "bobwilson@meta.com"
        assert result["confidence"] == 80
        assert result["known_company"] is True

    def test_known_company_apple(self) -> None:
        result = suggest_email("Alice", "Brown", "apple.com")
        assert result is not None
        assert result["email"] == "alice_brown@apple.com"
        assert result["confidence"] == 75
        assert result["known_company"] is True

    def test_unknown_domain_default_pattern(self) -> None:
        result = suggest_email("John", "Doe", "randomstartup.com")
        assert result is not None
        assert result["email"] == "john.doe@randomstartup.com"
        assert result["confidence"] == DEFAULT_CONFIDENCE
        assert result["known_company"] is False

    def test_includes_suggestions_list(self) -> None:
        result = suggest_email("John", "Doe", "amazon.com")
        assert result is not None
        assert "suggestions" in result
        assert len(result["suggestions"]) >= 4
        # Primary suggestion should be first
        assert result["suggestions"][0]["email"] == "john.doe@amazon.com"

    def test_accent_in_name(self) -> None:
        result = suggest_email("José", "García", "amazon.com")
        assert result is not None
        assert result["email"] == "jose.garcia@amazon.com"

    def test_hyphenated_name(self) -> None:
        result = suggest_email("Mary-Jane", "O'Connor", "microsoft.com")
        assert result is not None
        assert result["email"] == "maryjane.oconnor@microsoft.com"

    def test_domain_case_insensitive(self) -> None:
        result = suggest_email("John", "Doe", "AMAZON.COM")
        assert result is not None
        assert result["email"] == "john.doe@amazon.com"

    def test_missing_first_name_returns_none(self) -> None:
        assert suggest_email("", "Doe", "amazon.com") is None

    def test_missing_last_name_returns_none(self) -> None:
        assert suggest_email("John", "", "amazon.com") is None

    def test_missing_domain_returns_none(self) -> None:
        assert suggest_email("John", "Doe", "") is None

    def test_all_empty_returns_none(self) -> None:
        assert suggest_email("", "", "") is None


# --------------------------------------------------------------------------- #
# KNOWN_COMPANY_PATTERNS coverage
# --------------------------------------------------------------------------- #
class TestKnownCompanyPatterns:
    def test_all_patterns_have_valid_format(self) -> None:
        valid_formats = {"first.last", "firstlast", "flast", "first", "firstl", "first_last", "last.first"}
        for domain, (fmt, _) in KNOWN_COMPANY_PATTERNS.items():
            assert fmt in valid_formats, f"Invalid format '{fmt}' for domain {domain}"

    def test_all_confidences_are_reasonable(self) -> None:
        for domain, (_, confidence) in KNOWN_COMPANY_PATTERNS.items():
            assert 50 <= confidence <= 95, (
                f"Confidence {confidence} for {domain} outside expected range [50, 95]"
            )

    def test_blocked_domains_are_covered(self) -> None:
        """All pre-seeded SMTP-blocked domains should have a known pattern."""
        blocked_domains = [
            "google.com", "amazon.com", "meta.com", "microsoft.com", "apple.com",
            "nvidia.com", "salesforce.com", "oracle.com", "ibm.com", "intel.com",
            "cisco.com", "qualcomm.com", "intuit.com", "adobe.com", "sap.com",
            "cloudflare.com", "rbc.com", "td.com", "scotiabank.com", "bmo.com", "cibc.com",
        ]
        for domain in blocked_domains:
            assert domain in KNOWN_COMPANY_PATTERNS, (
                f"Blocked domain {domain} missing from KNOWN_COMPANY_PATTERNS"
            )

    @pytest.mark.parametrize("domain", list(KNOWN_COMPANY_PATTERNS.keys()))
    def test_every_known_pattern_generates_email(self, domain: str) -> None:
        """Every entry in the known patterns dict should produce a valid email."""
        result = suggest_email("Test", "User", domain)
        assert result is not None
        assert "@" in result["email"]
        assert result["email"].endswith(f"@{domain}")
