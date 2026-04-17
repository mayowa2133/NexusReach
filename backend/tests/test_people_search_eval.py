"""Labeled eval fixtures for job-aware people search ranking."""

from __future__ import annotations

import json
from pathlib import Path

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
