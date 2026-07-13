"""Structured requirement extraction and hard-eligibility behavior."""

from types import SimpleNamespace

from pydantic import ValidationError

from app.services.job_requirements import (
    evaluate_job_eligibility,
    extract_job_requirements,
    requirement_terms,
)
from app.schemas.profile import JobPreferences
from app.services.jobs.storage import hard_eligibility_decision


def _by_id(description: str) -> dict:
    return {item.id: item for item in extract_job_requirements(description)}


def test_extracts_mandatory_preferred_and_responsibility_with_source_spans():
    requirements = extract_job_requirements("""
Responsibilities
- Build forecasts in Excel and own financial reporting.
Requirements
- CPA required and 5+ years of experience.
Preferred Qualifications
- SAP experience is a plus.
""")
    by_id = {item.id: item for item in requirements}

    assert by_id["skill:excel"].kind == "responsibility"
    assert by_id["credential:cpa"].kind == "mandatory"
    assert by_id["credential:cpa"].criticality == "hard"
    assert by_id["experience:5_years_experience"].value == 5
    assert by_id["skill:sap"].kind == "preferred"
    assert by_id["credential:cpa"].source_span.startswith("CPA required")
    assert all(item.version == 1 for item in requirements)


def test_extracts_cross_category_hard_constraints():
    requirements = _by_id("""
Minimum Qualifications
- Active RN license required.
- Fluent in French.
- Must be available for rotating night shifts and on-call coverage.
- Up to 25% travel required.
- We cannot provide visa sponsorship.
""")

    assert requirements["license:rn_license"].criticality == "hard"
    assert requirements["language:french_language"].value == "French"
    assert requirements["schedule:shift_work"].kind == "mandatory"
    assert requirements["schedule:on_call"].kind == "mandatory"
    assert requirements["travel:travel_25"].value == 25
    assert requirements["work_authorization:no_sponsorship"].criticality == "hard"


def test_extracts_contract_duration_as_normalized_months():
    requirements = _by_id("""
Requirements
- This is a 26-week fixed-term contract.
""")

    duration = requirements["contract:contract_duration_6_months"]
    assert duration.value == 6
    assert duration.kind == "mandatory"
    assert duration.criticality == "hard"


def test_preferred_license_is_not_a_hard_failure():
    requirements = extract_job_requirements("""
Preferred Qualifications
- CPA preferred.
""")
    decision = evaluate_job_eligibility(
        job_data={"title": "Accountant", "company_name": "Acme"},
        requirements=requirements,
        evidence_text="Financial reporting and audit experience",
        preferences={},
    )

    assert decision.eligible is True
    assert decision.hard_failures == ()


def test_explicit_user_constraints_confirm_failures_and_unknowns():
    requirements = extract_job_requirements("""
Requirements
- Active RN license required.
- Fluent in French required.
- Up to 25% travel required.
- We cannot provide visa sponsorship.
""")
    decision = evaluate_job_eligibility(
        job_data={
            "title": "Registered Nurse",
            "company_name": "Northbridge Health",
            "description": "Night shift role",
        },
        requirements=requirements,
        evidence_text="Patient care and EHR experience. Active RN license.",
        preferences={
            "languages": ["English"],
            "max_travel_percent": 10,
            "requires_sponsorship": True,
        },
    )

    assert decision.eligible is False
    assert {item["id"] for item in decision.hard_failures} == {
        "language:french_language",
        "travel:travel_25",
        "work_authorization:no_sponsorship",
    }
    assert {item["id"] for item in decision.matched_constraints} == {
        "license:rn_license",
    }


def test_unknown_authorization_is_not_mislabeled_as_eligible_or_ineligible():
    requirements = extract_job_requirements("Requirements\nNo sponsorship available.")
    decision = evaluate_job_eligibility(
        job_data={"title": "Analyst", "company_name": "Acme"},
        requirements=requirements,
        evidence_text="",
        preferences={},
    )

    assert decision.eligible is None
    assert [item["id"] for item in decision.unknown_constraints] == [
        "work_authorization:no_sponsorship"
    ]


def test_excluded_employer_and_blocked_keyword_are_explicit():
    decision = evaluate_job_eligibility(
        job_data={
            "title": "Marketing Manager",
            "company_name": "Blocked Co",
            "description": "This is a commission-only role.",
        },
        requirements=[],
        evidence_text="",
        preferences={
            "excluded_employers": ["Blocked Co"],
            "blocked_keywords": ["commission-only"],
        },
    )

    assert decision.eligible is False
    assert decision.excluded_by == (
        "excluded_employer:Blocked Co",
        "blocked_keyword:commission-only",
    )


def test_confirmed_work_authorization_country_mismatch_is_hard_exclusion():
    decision = evaluate_job_eligibility(
        job_data={
            "title": "Analyst",
            "company_name": "Acme",
            "country_codes": ["US"],
        },
        requirements=[],
        evidence_text="",
        preferences={"work_authorization_countries": ["Canada"]},
    )

    assert decision.eligible is False
    assert decision.excluded_by == ("work_authorization_country:US",)


def test_requirement_terms_preserve_structure_filter():
    requirements = extract_job_requirements("""
Responsibilities
- Build dashboards in Tableau.
Requirements
- SQL required.
""")

    assert requirement_terms(requirements) == ["Tableau", "SQL"]
    assert requirement_terms(
        requirements, include_responsibilities=False
    ) == ["SQL"]


def test_profile_preferences_normalize_dedupe_and_validate_travel():
    preferences = JobPreferences(
        languages=[" French ", "french", "English"],
        excluded_employers=[" Acme, Inc. "],
        max_travel_percent=25,
        required_salary_currency=" cad ",
        required_salary_period="year",
        minimum_salary_confidence=0.75,
        minimum_contract_months=6,
    )

    assert preferences.languages == ["French", "English"]
    assert preferences.excluded_employers == ["Acme, Inc."]
    assert preferences.required_salary_currency == "CAD"
    try:
        JobPreferences(max_travel_percent=101)
    except ValidationError:
        pass
    else:
        raise AssertionError("travel above 100 must be rejected")


def test_salary_currency_period_and_confidence_are_explicit_hard_preferences():
    decision = evaluate_job_eligibility(
        job_data={
            "title": "Analyst",
            "company_name": "Acme",
            "salary_min": 80_000,
            "salary_currency": "USD",
            "salary_period": "year",
            "metadata_provenance": {"salary": {"confidence": 0.6}},
        },
        requirements=[],
        evidence_text="",
        preferences={
            "required_salary_currency": "CAD",
            "required_salary_period": "year",
            "minimum_salary_confidence": 0.75,
        },
    )

    assert decision.eligible is False
    assert {item["id"] for item in decision.hard_failures} == {
        "preference:required_salary_currency",
        "preference:minimum_salary_confidence",
    }
    assert {item["id"] for item in decision.matched_constraints} == {
        "preference:required_salary_period",
    }


def test_unknown_salary_metadata_stays_unknown_not_a_false_failure():
    decision = evaluate_job_eligibility(
        job_data={"title": "Analyst", "company_name": "Acme"},
        requirements=[],
        evidence_text="",
        preferences={
            "required_salary_currency": "CAD",
            "minimum_salary_confidence": 0.75,
        },
    )

    assert decision.eligible is None
    assert {item["id"] for item in decision.unknown_constraints} == {
        "preference:required_salary_currency",
        "preference:minimum_salary_confidence",
    }


def test_short_contract_is_rejected_and_unknown_duration_abstains():
    short_requirements = extract_job_requirements(
        "Requirements\nThis is a 3-month contract."
    )
    short = evaluate_job_eligibility(
        job_data={"title": "Analyst", "company_name": "Acme", "employment_type": "contract"},
        requirements=short_requirements,
        evidence_text="",
        preferences={"minimum_contract_months": 6},
    )
    unknown = evaluate_job_eligibility(
        job_data={"title": "Analyst", "company_name": "Acme", "employment_type": "contract"},
        requirements=extract_job_requirements("Contract role"),
        evidence_text="",
        preferences={"minimum_contract_months": 6},
    )

    assert short.eligible is False
    assert short.hard_failures[0]["id"] == "preference:minimum_contract_months"
    assert unknown.eligible is None
    assert unknown.unknown_constraints[0]["id"] == "preference:minimum_contract_months"


def test_storage_hard_filter_uses_explicit_profile_preferences():
    profile = SimpleNamespace(
        resume_parsed={"skills": ["Excel"]},
        job_preferences={"excluded_employers": ["Acme"]},
    )

    decision = hard_eligibility_decision(
        {
            "title": "Financial Analyst",
            "company_name": "Acme",
            "description": "Requirements\nExcel required.",
        },
        profile,
    )

    assert decision["eligible"] is False
    assert decision["excluded_by"] == ["excluded_employer:Acme"]


def test_missing_resume_keeps_required_license_unknown_instead_of_rejecting_job():
    profile = SimpleNamespace(resume_parsed=None, job_preferences={})

    decision = hard_eligibility_decision(
        {
            "title": "Registered Nurse",
            "company_name": "Hospital",
            "description": "Requirements\nActive RN license required.",
        },
        profile,
    )

    assert decision["eligible"] is None
    assert decision["hard_failures"] == []
    assert [item["id"] for item in decision["unknown_constraints"]] == [
        "license:rn_license"
    ]
