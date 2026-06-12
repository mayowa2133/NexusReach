"""Labeled eval fixtures for job-aware people search ranking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.people_service import _prepare_candidates
from app.utils.job_context import JobContext


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "people_search_eval"


def test_intuit_center_of_money_toronto_eval_fixture():
    fixture = json.loads((FIXTURE_DIR / "intuit_center_of_money_toronto.json").read_text())
    context = JobContext(**fixture["context"])

    recruiter_results = _prepare_candidates(
        fixture["recruiters"],
        company_name=fixture["company_name"],
        public_identity_slugs=fixture["public_identity_terms"],
        bucket="recruiters",
        context=context,
        limit=5,
    )
    manager_results = _prepare_candidates(
        fixture["hiring_managers"],
        company_name=fixture["company_name"],
        public_identity_slugs=fixture["public_identity_terms"],
        bucket="hiring_managers",
        context=context,
        limit=5,
    )

    assert recruiter_results[0]["full_name"] == fixture["expected"]["top_recruiter"]
    top_manager_names = [candidate["full_name"] for candidate in manager_results[:3]]
    assert fixture["expected"]["top_hiring_managers"][0] == top_manager_names[0]
    assert fixture["expected"]["top_hiring_managers"][1] in top_manager_names


@pytest.mark.parametrize(
    "fixture_name",
    [
        "lumastack_small_startup_austin.json",
        "northbridge_health_nursing_chicago.json",
        "zip_ambiguous_brand_new_york.json",
    ],
)
def test_company_shape_eval_fixtures(fixture_name):
    """Ranking evals across company shapes: small startup, non-tech enterprise,
    and an ambiguous brand where cross-company results must not win."""
    fixture = json.loads((FIXTURE_DIR / fixture_name).read_text())
    context = JobContext(**fixture["context"])

    recruiter_results = _prepare_candidates(
        fixture["recruiters"],
        company_name=fixture["company_name"],
        public_identity_slugs=fixture["public_identity_terms"],
        bucket="recruiters",
        context=context,
        limit=5,
    )
    manager_results = _prepare_candidates(
        fixture["hiring_managers"],
        company_name=fixture["company_name"],
        public_identity_slugs=fixture["public_identity_terms"],
        bucket="hiring_managers",
        context=context,
        limit=5,
    )

    assert recruiter_results, f"{fixture_name}: recruiter bucket came back empty"
    assert manager_results, f"{fixture_name}: hiring-manager bucket came back empty"
    assert recruiter_results[0]["full_name"] == fixture["expected"]["top_recruiter"]
    top_manager_names = [candidate["full_name"] for candidate in manager_results[:3]]
    expected_managers = fixture["expected"]["top_hiring_managers"]
    assert expected_managers[0] == top_manager_names[0]
    if len(expected_managers) > 1:
        assert expected_managers[1] in top_manager_names

    for name in fixture["expected"].get("must_not_rank_first", []):
        assert recruiter_results[0]["full_name"] != name
        assert (not manager_results) or manager_results[0]["full_name"] != name
