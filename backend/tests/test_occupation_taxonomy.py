"""Tests for the canonical occupation taxonomy."""

from __future__ import annotations

import pytest

from app.services.occupation_taxonomy import (
    OCCUPATION_TAG_PREFIX,
    OCCUPATIONS,
    classify_title,
    discover_queries_for_occupations,
    is_engineering_flavored,
    manager_title_seeds_for,
    newgrad_jobs_paths,
    occupation_by_key,
    occupation_keys_from_tags,
    occupation_tag,
    occupation_tags_for_job,
    outreach_playbook_for_keys,
    peer_title_seeds_for,
    startup_query_strings_for_occupations,
    team_keywords_for_department,
)


def test_v1_taxonomy_includes_all_23_categories() -> None:
    keys = {occ.key for occ in OCCUPATIONS}
    expected = {
        "software_engineering",
        "data_analyst",
        "marketing",
        "machine_learning_ai",
        "data_engineer",
        "business_analyst",
        "product_management",
        "creatives_design",
        "accounting_finance",
        "consulting",
        "engineering_development",
        "human_resources",
        "arts_entertainment",
        "management_executive",
        "customer_service_support",
        "legal_compliance",
        "sales",
        "public_sector_government",
        "education_training",
        "cybersecurity",
        "project_management",
        "healthcare",
        "supply_chain",
    }
    assert expected.issubset(keys)
    assert len(OCCUPATIONS) == len(expected)


def test_keys_are_unique_and_normalized() -> None:
    keys = [occ.key for occ in OCCUPATIONS]
    assert len(keys) == len(set(keys))
    for key in keys:
        assert key == key.lower()
        assert " " not in key
        assert "-" not in key


def test_occupation_by_key_handles_case_and_unknown() -> None:
    assert occupation_by_key("software_engineering").label == "Software Engineering"
    assert occupation_by_key("Software_Engineering").label == "Software Engineering"
    assert occupation_by_key("not_a_thing") is None


@pytest.mark.parametrize(
    "title, expected_key",
    [
        ("Senior Backend Engineer", "software_engineering"),
        ("Software Developer", "software_engineering"),
        ("Growth Marketing Manager", "marketing"),
        ("Data Analyst", "data_analyst"),
        ("Machine Learning Engineer", "machine_learning_ai"),
        ("Data Engineer", "data_engineer"),
        ("Product Manager", "product_management"),
        ("UX Designer", "creatives_design"),
        ("Financial Analyst", "accounting_finance"),
        ("Management Consultant", "consulting"),
        ("Mechanical Engineer", "engineering_development"),
        ("HR Business Partner", "human_resources"),
        ("Account Executive", "sales"),
        ("Registered Nurse", "healthcare"),
        ("Supply Chain Analyst", "supply_chain"),
        ("Cybersecurity Analyst", "cybersecurity"),
        ("Penetration Tester", "cybersecurity"),
        ("Technical Program Manager", "project_management"),
        ("General Counsel", "legal_compliance"),
        ("Customer Success Manager", "customer_service_support"),
    ],
)
def test_classify_title_picks_expected_occupation(title: str, expected_key: str) -> None:
    keys = classify_title(title)
    assert expected_key in keys, f"{title!r} → {keys}"


def test_classify_title_can_return_multiple_matches() -> None:
    keys = classify_title("Senior Machine Learning Software Engineer")
    assert "software_engineering" in keys
    assert "machine_learning_ai" in keys


def test_classify_title_word_boundary_isolates_short_aliases() -> None:
    # "ml engineer" must not fire on a word like "html engineer"
    keys = classify_title("HTML Email Specialist")
    assert "machine_learning_ai" not in keys


def test_classify_title_falls_back_to_description_when_title_blank() -> None:
    keys = classify_title("", "We are hiring a Sales Development Representative")
    assert "sales" in keys


def test_occupation_tag_round_trip() -> None:
    tag = occupation_tag("data_analyst")
    assert tag == f"{OCCUPATION_TAG_PREFIX}data_analyst"
    assert occupation_keys_from_tags([tag, "startup", "occupation:marketing"]) == [
        "data_analyst",
        "marketing",
    ]
    assert occupation_keys_from_tags(None) == []


def test_occupation_tags_for_job_prefers_explicit_keys() -> None:
    tags = occupation_tags_for_job(
        title="Marketing Manager",
        explicit_keys=["product_management"],
    )
    assert tags == [occupation_tag("product_management")]


def test_occupation_tags_for_job_falls_back_to_classifier() -> None:
    tags = occupation_tags_for_job(title="Senior Backend Engineer")
    assert tags == [occupation_tag("software_engineering")]


def test_discover_queries_for_data_analyst_excludes_swe_titles() -> None:
    queries = discover_queries_for_occupations(["data_analyst"])
    query_strings = [q["query"] for q in queries]
    assert "Software Engineer" not in query_strings
    assert "Data Analyst" in query_strings


def test_discover_queries_unknown_keys_fall_back_to_swe_default() -> None:
    queries = discover_queries_for_occupations(["definitely_not_real"])
    query_strings = [q["query"] for q in queries]
    assert "Software Engineer" in query_strings


def test_startup_query_strings_default_to_startup_friendly_set() -> None:
    queries = startup_query_strings_for_occupations(None)
    # Healthcare is not flagged startup_friendly, so its default queries
    # should not appear in the no-keys default.
    assert "Registered Nurse" not in queries
    # SWE is startup-friendly.
    assert "Software Engineer" in queries


def test_startup_query_strings_honor_explicit_non_startup_occupation() -> None:
    queries = startup_query_strings_for_occupations(["healthcare"])
    assert "Registered Nurse" in queries


def test_peer_title_seeds_routes_through_taxonomy() -> None:
    seeds = peer_title_seeds_for(["marketing"])
    assert "Marketing Manager" in seeds
    assert "Software Engineer" not in seeds


def test_manager_title_seeds_routes_through_taxonomy() -> None:
    seeds = manager_title_seeds_for(["marketing"])
    assert any("Marketing" in s for s in seeds)
    assert "Engineering Manager" not in seeds


def test_is_engineering_flavored_only_true_for_engineering_occupations() -> None:
    assert is_engineering_flavored(["software_engineering"]) is True
    assert is_engineering_flavored(["machine_learning_ai"]) is True
    assert is_engineering_flavored(["cybersecurity"]) is True
    assert is_engineering_flavored(["sales"]) is False
    assert is_engineering_flavored(["marketing"]) is False
    # Legacy "engineering" department fallback remains supported.
    assert is_engineering_flavored(None, department="engineering") is True
    assert is_engineering_flavored(None, department="sales") is False


def test_newgrad_jobs_paths_filters_known_paths_only() -> None:
    paths = newgrad_jobs_paths()
    # Existing paths from before the taxonomy refactor.
    assert "software-engineer-jobs" in paths
    assert "data-analyst" in paths
    assert "ux-designer" in paths
    assert "cyber-security" in paths


def test_every_v1_occupation_has_an_outreach_playbook() -> None:
    missing = [occ.key for occ in OCCUPATIONS if not (occ.outreach_playbook or "").strip()]
    assert missing == [], f"missing playbooks: {missing}"


def test_outreach_playbook_for_keys_preserves_caller_order() -> None:
    # When the caller supplies multiple matches, the first key wins.
    swe_playbook = outreach_playbook_for_keys(["software_engineering"])
    ml_playbook = outreach_playbook_for_keys(["machine_learning_ai"])
    assert swe_playbook is not None and ml_playbook is not None
    # ML listed first → ML playbook wins.
    assert outreach_playbook_for_keys(["machine_learning_ai", "software_engineering"]) == ml_playbook
    # SWE listed first → SWE playbook wins.
    assert outreach_playbook_for_keys(["software_engineering", "machine_learning_ai"]) == swe_playbook


def test_outreach_playbook_for_keys_via_classify_title_uses_canonical_order() -> None:
    # classify_title iterates OCCUPATIONS in canonical order, so the keys it
    # produces are already canonical-ordered. SWE precedes ML in canonical
    # order, so an ML Software Engineer job picks the SWE playbook.
    keys = classify_title("Senior Machine Learning Software Engineer")
    assert keys[0] == "software_engineering"
    playbook = outreach_playbook_for_keys(keys)
    swe_playbook = outreach_playbook_for_keys(["software_engineering"])
    assert playbook == swe_playbook


def test_outreach_playbook_for_keys_returns_none_for_unknown() -> None:
    assert outreach_playbook_for_keys(None) is None
    assert outreach_playbook_for_keys([]) is None
    assert outreach_playbook_for_keys(["bogus_key"]) is None


def test_team_keywords_for_department_falls_back_to_engineering() -> None:
    eng = team_keywords_for_department("engineering")
    assert "engineering" in eng
    unknown = team_keywords_for_department("totally_not_a_department")
    assert unknown == eng
