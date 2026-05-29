"""Proof tests for audit Batch 3 (MEDIUM) fixes — 2026-05-29.

Covers M1, M2, M3, M9, M10, M11, M14, M16, M17. (M5 board dedup, M7 semaphore,
M12 log level are covered by inspection / existing suites.)
"""

import pytest


# ---------------------------------------------------------------------------
# M1 — refresh never wipes enriched location/geocode with None
# ---------------------------------------------------------------------------
def test_m1_refresh_preserves_location_when_omitted():
    from app.models.job import Job
    from app.services.job_service import _refresh_existing_job

    job = Job(
        title="SWE",
        company_name="Acme",
        location="Austin, TX",
        country_codes=["US"],
        location_lat=30.27,
        location_lng=-97.74,
        location_geocode_label="Austin, TX, US",
        source="greenhouse",
    )
    # Refresh payload omits all location fields (a common partial re-fetch).
    _refresh_existing_job(
        job,
        {"title": "SWE", "company_name": "Acme", "source": "greenhouse"},
        fingerprint="fp",
        score=None,
        breakdown={},
        experience_level="mid",
    )
    assert job.country_codes == ["US"]
    assert job.location_lat == 30.27
    assert job.location_geocode_label == "Austin, TX, US"


def test_m1_refresh_updates_location_when_provided():
    from app.models.job import Job
    from app.services.job_service import _refresh_existing_job

    job = Job(title="SWE", company_name="Acme", country_codes=["US"], source="greenhouse")
    _refresh_existing_job(
        job,
        {
            "title": "SWE",
            "company_name": "Acme",
            "source": "greenhouse",
            "country_codes": ["CA"],
        },
        fingerprint="fp",
        score=None,
        breakdown={},
        experience_level="mid",
    )
    assert job.country_codes == ["CA"]


# ---------------------------------------------------------------------------
# M2 — Lever company slug humanized
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("match-group", "Match Group"),
        ("spotify", "Spotify"),
        ("acme_corp", "Acme Corp"),
    ],
)
def test_m2_humanize_company_slug(slug, expected):
    from app.clients.ats_client import _humanize_company_slug

    assert _humanize_company_slug(slug) == expected


# ---------------------------------------------------------------------------
# M3 — JSearch composes full location
# ---------------------------------------------------------------------------
def test_m3_compose_location_keeps_specificity():
    from app.clients.jsearch_client import _compose_location

    assert _compose_location("Austin", "TX", "US") == "Austin, TX, US"
    assert _compose_location("", "TX", "US") == "TX, US"
    assert _compose_location("Austin", "Austin", "US") == "Austin, US"  # dedupes
    assert _compose_location(None, None, None) == ""


# ---------------------------------------------------------------------------
# M8 — round-robin mix doesn't waste slots on duplicates
# ---------------------------------------------------------------------------
def test_m8_balanced_mix_does_not_starve_group_on_duplicate():
    from app.services.people_service import _balanced_candidate_mix

    # Group A's first item duplicates group B's first item. With the old shared
    # index, A's unique second item could be skipped. Now every unique candidate
    # across both groups is included.
    group_a = [{"linkedin_url": "dup"}, {"linkedin_url": "a2"}, {"linkedin_url": "a3"}]
    group_b = [{"linkedin_url": "dup"}, {"linkedin_url": "b2"}]

    mixed = _balanced_candidate_mix(group_a, group_b, limit=10)
    urls = [c["linkedin_url"] for c in mixed]

    # "dup" appears once; every other unique candidate is present.
    assert urls.count("dup") == 1
    assert set(urls) == {"dup", "a2", "a3", "b2"}


# ---------------------------------------------------------------------------
# M9 — recruiter-lead detection ignores location
# ---------------------------------------------------------------------------
def test_m9_recruiter_lead_ignores_location_field():
    from app.services.people_service import _has_recruiter_lead_candidate

    # A recruiter located in "Canada" but with no lead/seniority signal must NOT
    # be treated as a recruiter lead just because of their location.
    candidates = [
        {"title": "Recruiter", "snippet": "Recruiter at Acme", "location": "Toronto, Canada"}
    ]
    assert _has_recruiter_lead_candidate(candidates) is False

    # A genuine lead title is still detected.
    lead = [{"title": "Head of Talent Acquisition", "snippet": "", "location": "Remote"}]
    assert _has_recruiter_lead_candidate(lead) is True


# ---------------------------------------------------------------------------
# M10 — detached person copy does not share ORM state
# ---------------------------------------------------------------------------
def test_m10_detached_person_copy_has_own_state():
    from app.models.person import Person
    from app.services.people_service import _detached_person_copy

    original = Person(full_name="Jane Doe", title="Staff Engineer", person_type="peer")
    original.usefulness_score = 42  # dynamic ranking attribute
    clone = _detached_person_copy(original)

    # Distinct SQLAlchemy instance state (the M10 bug shared it).
    assert clone.__dict__["_sa_instance_state"] is not original.__dict__["_sa_instance_state"]
    # Column values + dynamic attributes are carried over.
    assert clone.full_name == "Jane Doe"
    assert clone.usefulness_score == 42
    # Mutating the clone doesn't touch the original.
    clone.person_type = "hiring_manager"
    assert original.person_type == "peer"


# ---------------------------------------------------------------------------
# M11 — The Org timeout uses config
# ---------------------------------------------------------------------------
def test_m11_theorg_timeout_uses_configured_value():
    import inspect

    from app.services import people_service

    src = inspect.getsource(people_service._recover_title_from_theorg_page)
    assert "settings.theorg_timeout_seconds" in src
    assert "timeout_seconds=20" not in src


# ---------------------------------------------------------------------------
# M14 — email body is HTML-escaped
# ---------------------------------------------------------------------------
def test_m14_gmail_body_escapes_html():
    from app.services.gmail_service import _body_to_html

    out = _body_to_html("Hi <script>alert(1)</script> & welcome")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&amp;" in out
    # Newline formatting still applied around escaped content.
    assert _body_to_html("a\n\nb") == "<p>a</p><p>b</p>"


def test_m14_outlook_body_escapes_html():
    from app.services.outlook_service import _body_to_html

    out = _body_to_html("<b>x</b>")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


# ---------------------------------------------------------------------------
# M16 — Workday paginates beyond 20
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_m16_workday_paginates_with_offset():
    import httpx

    from app.clients import workday_client

    seen_offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        import json

        offset = json.loads(body)["offset"]
        seen_offsets.append(offset)
        # 25 total jobs across two pages of 20.
        if offset == 0:
            postings = [
                {"title": f"Job {i}", "externalPath": f"/job/{i}", "postedOn": ""}
                for i in range(20)
            ]
        else:
            postings = [
                {"title": f"Job {i}", "externalPath": f"/job/{i}", "postedOn": ""}
                for i in range(20, 25)
            ]
        return httpx.Response(200, json={"jobPostings": postings, "total": 25})

    transport = httpx.MockTransport(handler)
    orig_client = workday_client.httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    workday_client.httpx.AsyncClient = _client_factory
    try:
        jobs = await workday_client.search_workday(
            "nvidia", "wd5", "Careers", "NVIDIA", limit=25
        )
    finally:
        workday_client.httpx.AsyncClient = orig_client

    # Paged past the first 20 (offsets 0 and 20 were requested).
    assert 0 in seen_offsets and 20 in seen_offsets
    assert len(jobs) == 25


# ---------------------------------------------------------------------------
# M17 — search-preference location normalization
# ---------------------------------------------------------------------------
def test_m17_normalized_pref_location_collapses_variants():
    from app.services.job_service import _normalized_pref_location

    a = _normalized_pref_location("New York")
    b = _normalized_pref_location("  new york ")
    assert a == b
    assert _normalized_pref_location("") == ""
    assert _normalized_pref_location(None) == ""
