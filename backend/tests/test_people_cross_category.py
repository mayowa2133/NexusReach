"""Cross-category regressions for company-level people discovery."""

import uuid
from types import SimpleNamespace

import pytest

from app.services.people.buckets import _finalize_bucketed
from app.services.people.candidates import _cached_candidate_ready
from app.services.people.context import _build_roles_context
from app.services.people.titles import (
    _companywide_manager_titles,
    _companywide_peer_titles,
)


@pytest.mark.parametrize(
    "role,occupation,department,expected_peer,forbidden",
    [
        ("Registered Nurse", "healthcare", "healthcare", "Registered Nurse", "Software Engineer"),
        ("Financial Analyst", "accounting_finance", "finance", "Financial Analyst", "Software Engineer"),
        ("Marketing Manager", "marketing", "marketing", "Marketing Manager", "Software Engineer"),
        ("Attorney", "legal_compliance", "legal", "Attorney", "Software Engineer"),
        ("Teacher", "education_training", "education", "Teacher", "Software Engineer"),
    ],
)
def test_company_roles_use_canonical_occupation_context(
    role, occupation, department, expected_peer, forbidden
):
    context = _build_roles_context([role])

    assert context is not None
    assert occupation in context.occupation_keys
    assert context.department == department
    assert expected_peer in _companywide_peer_titles(context)
    assert forbidden not in _companywide_peer_titles(context)
    assert all("Engineering" not in title for title in _companywide_manager_titles(context))


def test_unknown_company_role_stays_neutral_instead_of_engineering():
    context = _build_roles_context(["Chief Puzzle Wrangler"])

    assert context is not None
    assert context.department == ""
    assert context.occupation_keys == []


def _peer(name: str, title: str):
    return SimpleNamespace(
        id=uuid.uuid4(),
        full_name=name,
        title=title,
        linkedin_url=f"https://linkedin.com/in/{name.lower().replace(' ', '-')}",
        current_company_verified=True,
        match_quality="direct",
        fallback_reason=None,
        employment_status="current",
        org_level="ic",
        person_type="peer",
        usefulness_score=70,
        warm_path_type=None,
        profile_data={},
    )


def test_final_peer_sort_respects_nontechnical_context():
    context = _build_roles_context(["Registered Nurse"])
    peers = [
        _peer("Sam Engineer", "Software Engineer"),
        _peer("Nia Nurse", "Registered Nurse"),
    ]

    result = _finalize_bucketed(
        {"recruiters": [], "hiring_managers": [], "peers": peers},
        target_count_per_bucket=2,
        context=context,
    )

    assert [person.full_name for person in result["peers"]] == [
        "Nia Nurse", "Sam Engineer",
    ]


def test_final_peer_set_diversifies_within_same_trust_tier():
    context = _build_roles_context(["Registered Nurse"])
    first = _peer("A Nurse", "Registered Nurse")
    duplicate = _peer("B Nurse", "Registered Nurse")
    distinct = _peer("C Specialist", "Clinical Nurse Specialist")
    first.source = "google_cse"
    duplicate.source = "google_cse"
    distinct.source = "company_site"

    result = _finalize_bucketed(
        {
            "recruiters": [],
            "hiring_managers": [],
            "peers": [first, duplicate, distinct],
        },
        target_count_per_bucket=3,
        context=context,
    )

    assert [person.full_name for person in result["peers"]] == [
        "A Nurse",
        "C Specialist",
        "B Nurse",
    ]


def test_cache_hit_must_pass_company_employment_and_bucket_preflight():
    base = {
        "full_name": "Nia Nurse",
        "title": "Registered Nurse",
        "company_name": "Northbridge Health",
        "source": "apollo",
        "snippet": "Registered Nurse at Northbridge Health",
    }
    assert _cached_candidate_ready(
        base,
        company_name="Northbridge Health",
        requested_titles=["Registered Nurse"],
        public_identity_terms=None,
    )
    assert not _cached_candidate_ready(
        {**base, "company_name": "Different Hospital", "snippet": "Registered Nurse at Different Hospital"},
        company_name="Northbridge Health",
        requested_titles=["Registered Nurse"],
        public_identity_terms=None,
    )
    assert not _cached_candidate_ready(
        {**base, "snippet": "Former Registered Nurse at Northbridge Health"},
        company_name="Northbridge Health",
        requested_titles=["Registered Nurse"],
        public_identity_terms=None,
    )
    assert not _cached_candidate_ready(
        {**base, "title": "Software Engineer"},
        company_name="Northbridge Health",
        requested_titles=["Registered Nurse"],
        public_identity_terms=None,
    )
