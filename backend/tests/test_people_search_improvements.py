"""Tests for people search improvement features:
- Talent Scout keyword
- Level-specific peer titles
- New grad team keyword injection
- Location-aware ranking
- Recency ranking
- iCIMS URL parsing
"""

from datetime import datetime, timedelta, timezone

from app.clients.ats_client import _parse_icims_url, parse_ats_job_url
from app.services.people_service import (
    RECRUITER_TITLE_KEYWORDS,
    _compute_usefulness_score,
    _location_match_rank,
    _recency_rank,
)
from app.utils.job_context import JobContext, _build_peer_titles, _build_recruiter_titles, extract_job_context


# ---------------------------------------------------------------------------
# 1. "Talent Scout" keyword
# ---------------------------------------------------------------------------


def test_talent_scout_in_recruiter_keywords():
    assert "talent scout" in RECRUITER_TITLE_KEYWORDS


def test_talent_scout_in_recruiter_titles():
    titles = _build_recruiter_titles("engineering", [], early_career=False)
    assert "Talent Scout" in titles


def test_university_talent_scout_in_early_career_recruiter_titles():
    titles = _build_recruiter_titles("engineering", [], early_career=True)
    assert "University Talent Scout" in titles
    assert "Talent Scout" in titles


# ---------------------------------------------------------------------------
# 2. Level-specific peer titles for early career
# ---------------------------------------------------------------------------


def test_early_career_peer_titles_include_level_specific():
    titles = _build_peer_titles("Software Engineer", [], "junior", "engineering")
    assert "Software Engineer I" in titles
    assert "SWE I" in titles
    assert "Junior Software Engineer" in titles
    assert "New Grad Software Engineer" in titles


def test_non_early_career_peer_titles_omit_level_specific():
    titles = _build_peer_titles("Software Engineer", [], "senior", "engineering")
    assert "Software Engineer I" not in titles
    assert "SWE I" not in titles
    assert "New Grad Software Engineer" not in titles


# ---------------------------------------------------------------------------
# 3. "new grad" team keyword injection
# ---------------------------------------------------------------------------


def test_extract_job_context_injects_new_grad_keyword():
    context = extract_job_context("Graduate 2026 Software Engineer I, US")
    assert context.early_career is True
    assert "new grad" in context.team_keywords


def test_extract_job_context_non_early_career_no_new_grad():
    context = extract_job_context("Senior Software Engineer")
    assert context.early_career is False
    assert "new grad" not in context.team_keywords


def test_extract_job_context_seniority_for_graduate():
    context = extract_job_context("Graduate 2026 Software Engineer I, US")
    assert context.seniority == "junior"


# ---------------------------------------------------------------------------
# 4. Location-aware ranking
# ---------------------------------------------------------------------------


def test_location_match_rank_exact_match():
    ctx = JobContext(department="engineering", job_locations=["San Francisco, CA"])
    candidate = {"city": "San Francisco"}
    assert _location_match_rank(candidate, context=ctx) == 0


def test_location_match_rank_substring_match():
    ctx = JobContext(department="engineering", job_locations=["San Francisco, CA"])
    candidate = {"location": "San Francisco, California, United States"}
    assert _location_match_rank(candidate, context=ctx) == 0


def test_location_match_rank_no_match():
    ctx = JobContext(department="engineering", job_locations=["San Francisco, CA"])
    candidate = {"city": "Chicago"}
    assert _location_match_rank(candidate, context=ctx) == 1


def test_location_match_rank_no_candidate_location():
    ctx = JobContext(department="engineering", job_locations=["San Francisco, CA"])
    candidate = {"full_name": "Test Person"}
    assert _location_match_rank(candidate, context=ctx) == 1


def test_location_match_rank_no_job_locations():
    ctx = JobContext(department="engineering", job_locations=[])
    candidate = {"city": "San Francisco"}
    assert _location_match_rank(candidate, context=ctx) == 1


def test_location_match_rank_profile_data_location():
    ctx = JobContext(department="engineering", job_locations=["New York, NY"])
    candidate = {"profile_data": {"location": "New York City"}}
    assert _location_match_rank(candidate, context=ctx) == 0


def test_location_match_rank_multiple_job_locations():
    ctx = JobContext(department="engineering", job_locations=["San Francisco, CA", "New York, NY", "Seattle, WA"])
    assert _location_match_rank({"city": "Seattle"}, context=ctx) == 0
    assert _location_match_rank({"city": "Austin"}, context=ctx) == 1


# ---------------------------------------------------------------------------
# 5. Recency ranking
# ---------------------------------------------------------------------------


def test_recency_rank_fresh_cache():
    candidate = {"profile_data": {"cache_freshness": "fresh"}}
    assert _recency_rank(candidate) == 0


def test_recency_rank_stale_cache():
    candidate = {"profile_data": {"cache_freshness": "stale"}}
    assert _recency_rank(candidate) == 1


def test_recency_rank_recent_employment():
    recent_date = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    candidate = {"employment_start_date": recent_date}
    assert _recency_rank(candidate) == 0


def test_recency_rank_old_employment():
    old_date = (datetime.now(timezone.utc) - timedelta(days=1500)).isoformat()
    candidate = {"employment_start_date": old_date}
    assert _recency_rank(candidate) == 1


def test_recency_rank_no_signal():
    candidate = {"full_name": "Test Person"}
    assert _recency_rank(candidate) == 1


# ---------------------------------------------------------------------------
# 6. Usefulness score includes location and recency
# ---------------------------------------------------------------------------


def test_usefulness_score_location_boost():
    ctx = JobContext(department="engineering", job_locations=["San Francisco, CA"])
    base = {
        "title": "Technical Recruiter",
        "source": "apollo",
        "linkedin_url": "https://linkedin.com/in/test",
        "_employment_status": "current",
    }
    no_location = dict(base)
    with_location = {**base, "city": "San Francisco"}
    score_without = _compute_usefulness_score(no_location, bucket="recruiters", context=ctx, company_name="Uber")
    score_with = _compute_usefulness_score(with_location, bucket="recruiters", context=ctx, company_name="Uber")
    assert score_with > score_without


def test_usefulness_score_recency_boost_peers():
    ctx = JobContext(department="engineering", seniority="junior", early_career=True)
    base = {
        "title": "Software Engineer",
        "source": "apollo",
        "linkedin_url": "https://linkedin.com/in/test",
        "_employment_status": "current",
    }
    no_recency = dict(base)
    with_recency = {**base, "profile_data": {"cache_freshness": "fresh"}}
    score_without = _compute_usefulness_score(no_recency, bucket="peers", context=ctx, company_name="Uber")
    score_with = _compute_usefulness_score(with_recency, bucket="peers", context=ctx, company_name="Uber")
    assert score_with > score_without


# ---------------------------------------------------------------------------
# 7. iCIMS URL parsing
# ---------------------------------------------------------------------------


def test_parse_icims_url_basic():
    result = _parse_icims_url("https://university-uber.icims.com/jobs/158009/job")
    assert result is not None
    assert result.ats_type == "icims"
    assert result.company_slug == "uber"
    assert result.external_id == "icims_158009"
    assert result.exact_url_only is True


def test_parse_icims_url_with_query_params():
    result = _parse_icims_url(
        "https://university-uber.icims.com/jobs/158009/job?mobile=true&needsRedirect=false"
    )
    assert result is not None
    assert result.ats_type == "icims"
    assert result.company_slug == "uber"
    assert result.external_id == "icims_158009"


def test_parse_icims_url_simple_subdomain():
    result = _parse_icims_url("https://acme.icims.com/jobs/12345/job")
    assert result is not None
    assert result.company_slug == "acme"
    assert result.external_id == "icims_12345"


def test_parse_icims_url_careers_prefix():
    result = _parse_icims_url("https://careers-google.icims.com/jobs/99999/engineer")
    assert result is not None
    assert result.company_slug == "google"
    assert result.external_id == "icims_99999"


def test_parse_icims_url_not_icims():
    assert _parse_icims_url("https://greenhouse.io/jobs/123") is None
    assert _parse_icims_url("https://lever.co/company/jobs/123") is None


def test_parse_ats_job_url_recognizes_icims():
    """iCIMS URLs should be parsed as iCIMS, not fall through to generic_exact."""
    result = parse_ats_job_url("https://university-uber.icims.com/jobs/158009/job")
    assert result is not None
    assert result.ats_type == "icims"


# ---------------------------------------------------------------------------
# 8. JobContext.job_locations field
# ---------------------------------------------------------------------------


def test_job_context_has_job_locations():
    ctx = JobContext(department="engineering", job_locations=["SF", "NYC"])
    assert ctx.job_locations == ["SF", "NYC"]


def test_job_context_default_empty_locations():
    ctx = JobContext(department="engineering")
    assert ctx.job_locations == []
