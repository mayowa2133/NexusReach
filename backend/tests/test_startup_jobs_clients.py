from __future__ import annotations

import json
from pathlib import Path

from app.clients.conviction_jobs_client import parse_jobs_page_html as parse_conviction_jobs_page_html
from app.clients.speedrun_jobs_client import parse_companies_payload
from app.clients.ventureloop_jobs_client import parse_jobs_page_html as parse_ventureloop_jobs_page_html
from app.clients.wellfound_jobs_client import parse_jobs_page_html as parse_wellfound_jobs_page_html
from app.clients.yc_jobs_client import parse_jobs_page_html as parse_yc_jobs_page_html

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "startup_jobs"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


def test_parse_yc_jobs_page_html():
    jobs = parse_yc_jobs_page_html(_fixture("yc_jobs.html"), query="product engineer")

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "yc_jobs"
    assert job["company_name"] == "Cartesia"
    assert job["remote"] is True
    assert job["salary_min"] == 150000.0
    assert job["salary_max"] == 190000.0
    assert "startup" in (job["tags"] or [])


def test_parse_wellfound_jobs_page_html():
    jobs = parse_wellfound_jobs_page_html(_fixture("wellfound_jobs.html"), query="product engineer")

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "wellfound"
    assert job["company_name"] == "Northstar"
    assert job["remote"] is True
    assert job["posted_at"] == "2026-04-03T00:00:00Z"


def test_parse_ventureloop_jobs_page_html():
    jobs = parse_ventureloop_jobs_page_html(_fixture("ventureloop_jobs.html"), query="product manager")

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "ventureloop"
    assert job["company_name"] == "Collective Health"
    assert job["remote"] is True
    assert job["external_id"] == "ventureloop_2983316"
    assert job["posted_at"] == "2026-04-03T00:00:00+00:00"


def test_parse_conviction_jobs_page_html():
    startups = parse_conviction_jobs_page_html(_fixture("conviction_jobs.html"))

    assert len(startups) == 2
    assert startups[0]["company_name"] == "Corridor"
    assert startups[0]["career_url"] == "https://jobs.ashbyhq.com/corridor"
    assert startups[0]["roles"][0]["title"] == "Infra Engineer"


def test_parse_speedrun_companies_payload():
    payload = json.loads(_fixture("speedrun_companies.json"))
    companies = parse_companies_payload(payload)

    assert len(companies) == 2
    assert companies[0]["company_name"] == "Cartesia"
    assert companies[0]["website_url"] == "https://cartesia.ai"
    assert companies[0]["location"] == "San Francisco, CA, United States"
