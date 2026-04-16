"""Location-sensitive ranking evals for job-aware people search."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.people_service import _prepare_candidates
from app.utils.job_context import JobContext, build_job_geo_context


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "people_search_eval"
    / "intuit_center_of_money_toronto.json"
)


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _build_context(payload: dict) -> JobContext:
    job = payload["job"]
    geo = build_job_geo_context([job["location"]])
    return JobContext(
        department=job["department"],
        team_keywords=job["team_keywords"],
        seniority=job["seniority"],
        job_locations=[job["location"]],
        job_geo_terms=geo["terms"],
        job_geo_cities=geo["cities"],
        job_geo_metros=geo["metros"],
        job_geo_regions=geo["regions"],
        job_geo_countries=geo["countries"],
    )


def test_intuit_eval_prefers_toronto_recruiter_and_managers():
    payload = _load_fixture()
    context = _build_context(payload)

    ranked_recruiters = _prepare_candidates(
        payload["recruiters"],
        company_name=payload["job"]["company_name"],
        bucket="recruiters",
        context=context,
        limit=5,
    )
    ranked_managers = _prepare_candidates(
        payload["hiring_managers"],
        company_name=payload["job"]["company_name"],
        bucket="hiring_managers",
        context=context,
        limit=5,
    )

    recruiter_names = [candidate["full_name"] for candidate in ranked_recruiters]
    manager_names = [candidate["full_name"] for candidate in ranked_managers[:3]]

    assert recruiter_names[0] == payload["expected_top_recruiter"]
    assert set(payload["expected_top_hiring_managers"]).issubset(set(manager_names))
