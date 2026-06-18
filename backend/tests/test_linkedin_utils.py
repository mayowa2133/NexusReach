"""Unit tests for the shared LinkedIn SERP-title parser.

`parse_linkedin_serp_title` is the single source of truth used by the
search-provider result parsers (Brave/Google/SearXNG) and the public-web
profile enricher.
"""

from app.utils.linkedin import parse_linkedin_serp_title


def test_name_title_company():
    assert parse_linkedin_serp_title("Jane Doe - Staff Engineer - Stripe | LinkedIn") == (
        "Jane Doe",
        "Staff Engineer",
        "Stripe",
    )


def test_title_at_company():
    assert parse_linkedin_serp_title("John Smith - Senior Recruiter at Figma | LinkedIn") == (
        "John Smith",
        "Senior Recruiter",
        "Figma",
    )


def test_en_dash_separator():
    assert parse_linkedin_serp_title("Ana Reyes – Product Manager – Notion | LinkedIn") == (
        "Ana Reyes",
        "Product Manager",
        "Notion",
    )


def test_name_only():
    assert parse_linkedin_serp_title("Sam Lee | LinkedIn") == ("Sam Lee", "", "")


def test_name_title_no_company():
    assert parse_linkedin_serp_title("Lee Park - Designer | LinkedIn") == ("Lee Park", "Designer", "")


def test_trailing_junk_after_linkedin_is_dropped():
    # Real SERP titles sometimes append connection counts etc. after "LinkedIn".
    assert parse_linkedin_serp_title(
        "Jane Doe - Staff Engineer - Stripe | LinkedIn · 500+ connections"
    ) == ("Jane Doe", "Staff Engineer", "Stripe")


def test_dash_linkedin_suffix_variant():
    assert parse_linkedin_serp_title("Jane Doe - Staff Engineer - LinkedIn") == (
        "Jane Doe",
        "Staff Engineer",
        "",
    )


def test_empty_input():
    assert parse_linkedin_serp_title("") == ("", "", "")


def test_hyphenated_name_not_split():
    # Hyphen-minus inside a name (no surrounding spaces) must not split.
    assert parse_linkedin_serp_title("Anne-Marie Smith - Engineer - Acme | LinkedIn") == (
        "Anne-Marie Smith",
        "Engineer",
        "Acme",
    )
