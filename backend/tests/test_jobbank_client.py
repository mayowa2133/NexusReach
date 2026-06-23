"""Tests for the Job Bank Canada (jobbank.gc.ca) scrape client."""

import httpx
import pytest

from app.clients import jobbank_client
from app.clients.jobbank_client import (
    _clean_location,
    _parse_posted_at,
    _parse_results,
)


def _article(job_id: str, noc: str, business: str, location: str,
             salary: str, date: str, telework: str | None) -> str:
    telework_span = f'<span class="telework">{telework}</span>' if telework else ""
    return f"""
    <article id="article-{job_id}" class="action-buttons">
      <a class="resultJobItem" href="/jobsearch/jobposting/{job_id};jsessionid=ABC?source=searchresults">
        <h3 class="title">
          <span class="flag">{telework_span}<span class="appmethod">Direct Apply</span></span>
          <span class="noctitle">{noc}</span>
        </h3>
        <ul>
          <li class="date">{date}</li>
          <li class="business">{business}</li>
          <li class="location"><span class="wb-inv">Location</span>{location}</li>
          <li class="salary"><span class="wb-inv">Salary</span>Salary {salary}</li>
        </ul>
      </a>
    </article>
    """


SAMPLE_HTML = "<html><body>" + "".join([
    _article("49681586", "software developer", "Binary Stream Software Inc.",
             "Burnaby (BC)", "$52.40 hourly", "June 09, 2026", "Hybrid"),
    _article("49766397", "registered nurse", "Marine Health",
             "Halifax (NS)", "$42.00 hourly", "June 22, 2026", None),
    _article("49717492", "data analyst", "Remote Co",
             "Toronto (ON)", "$90,000 annually", "June 15, 2026", "Remote"),
]) + "</body></html>"


def test_parse_results_extracts_all_fields():
    jobs = _parse_results(SAMPLE_HTML)
    assert len(jobs) == 3
    first = jobs[0]
    assert first["external_id"] == "jobbank_49681586"
    assert first["title"] == "software developer"
    assert first["company_name"] == "Binary Stream Software Inc."
    assert first["location"] == "Burnaby, BC, Canada"
    assert first["work_mode"] == "hybrid"
    assert first["remote"] is False
    # jsessionid + query string stripped to a stable canonical posting URL
    assert first["url"] == "https://www.jobbank.gc.ca/jobsearch/jobposting/49681586"
    assert first["apply_url"] == first["url"]
    assert first["posted_at"] == "2026-06-09"
    assert first["salary"] == "$52.40 hourly"  # "Salary" label stripped
    assert first["source"] == "jobbank"


def test_parse_results_detects_remote_and_onsite():
    jobs = {j["external_id"]: j for j in _parse_results(SAMPLE_HTML)}
    onsite = jobs["jobbank_49766397"]
    assert onsite["work_mode"] == "onsite"
    assert onsite["remote"] is False
    remote = jobs["jobbank_49717492"]
    assert remote["work_mode"] == "remote"
    assert remote["remote"] is True


def test_parse_results_skips_articles_without_title():
    html = '<article id="article-1"><h3 class="title"></h3></article>'
    assert _parse_results(html) == []


def test_clean_location_normalizes_province_and_appends_canada():
    assert _clean_location("Toronto (ON)") == "Toronto, ON, Canada"
    assert _clean_location("Vancouver") == "Vancouver, Canada"
    assert _clean_location("Montréal, QC, Canada") == "Montréal, QC, Canada"
    assert _clean_location("") == "Canada"
    assert _clean_location(None) == "Canada"


def test_parse_posted_at_parses_long_form_date():
    assert _parse_posted_at("June 09, 2026") == "2026-06-09"
    assert _parse_posted_at("garbage") is None
    assert _parse_posted_at("") is None


@pytest.mark.asyncio
async def test_search_jobbank_fails_soft_on_network_error(monkeypatch):
    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(jobbank_client.httpx, "AsyncClient", _BoomClient)
    assert await jobbank_client.search_jobbank("developer", location="Toronto") == []


@pytest.mark.asyncio
async def test_search_jobbank_dedupes_and_caps_to_limit(monkeypatch):
    class _PageClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            # Every page returns the same 3 articles -> de-dupe to 3.
            return httpx.Response(200, text=SAMPLE_HTML)

    monkeypatch.setattr(jobbank_client.httpx, "AsyncClient", _PageClient)
    jobs = await jobbank_client.search_jobbank("developer", location="Toronto", limit=50)
    assert len(jobs) == 3
    assert len({j["external_id"] for j in jobs}) == 3
