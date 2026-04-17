"""Tests for the job alert notification service."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.job_alert import JobAlertPreference
from app.services.job_alert_service import (
    _render_digest_html,
    _render_digest_text,
    find_new_jobs_for_alert,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_job(
    *,
    title: str = "Software Engineer",
    company_name: str = "Google",
    location: str = "Mountain View, CA",
    url: str = "https://example.com/jobs/1",
    created_at: datetime | None = None,
) -> MagicMock:
    job = MagicMock()
    job.id = uuid.uuid4()
    job.title = title
    job.company_name = company_name
    job.location = location
    job.url = url
    job.description = f"Join {company_name} as a {title}"
    job.user_id = uuid.uuid4()
    job.created_at = created_at or datetime.now(timezone.utc)
    return job


def _make_prefs(
    *,
    enabled: bool = True,
    watched_companies: list[str] | None = None,
    use_starred_companies: bool = False,
    keyword_filters: list[str] | None = None,
) -> JobAlertPreference:
    prefs = JobAlertPreference()
    prefs.enabled = enabled
    prefs.watched_companies = watched_companies or []
    prefs.use_starred_companies = use_starred_companies
    prefs.keyword_filters = keyword_filters or []
    prefs.frequency = "daily"
    prefs.email_provider = "connected"
    prefs.last_digest_sent_at = None
    prefs.total_alerts_sent = 0
    return prefs


# ---------------------------------------------------------------------------
# Digest rendering tests
# ---------------------------------------------------------------------------


class TestDigestRendering:
    def test_html_contains_job_titles(self):
        jobs = [
            _make_job(title="Frontend Engineer", company_name="Meta"),
            _make_job(title="Backend Engineer", company_name="Google"),
        ]
        html = _render_digest_html(jobs, "user@example.com")
        assert "Frontend Engineer" in html
        assert "Backend Engineer" in html
        assert "Meta" in html
        assert "Google" in html

    def test_html_groups_by_company(self):
        jobs = [
            _make_job(title="SWE 1", company_name="Apple"),
            _make_job(title="SWE 2", company_name="Apple"),
            _make_job(title="PM", company_name="Google"),
        ]
        html = _render_digest_html(jobs, "user@example.com")
        assert "Apple" in html
        assert "Google" in html
        assert "3 new postings" in html

    def test_html_single_job_grammar(self):
        jobs = [_make_job()]
        html = _render_digest_html(jobs, "user@example.com")
        assert "1 new posting " in html
        assert "postings" not in html

    def test_text_contains_jobs(self):
        jobs = [_make_job(title="ML Engineer", company_name="DeepMind")]
        text = _render_digest_text(jobs)
        assert "ML Engineer" in text
        assert "DeepMind" in text
        assert "1 new posting" in text

    def test_text_includes_url(self):
        jobs = [_make_job(url="https://jobs.example.com/123")]
        text = _render_digest_text(jobs)
        assert "https://jobs.example.com/123" in text


# ---------------------------------------------------------------------------
# Job matching tests
# ---------------------------------------------------------------------------


class TestJobMatching:
    @pytest.mark.anyio
    async def test_matches_watched_company(self):
        prefs = _make_prefs(watched_companies=["Google"])
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        google_job = _make_job(company_name="Google")
        meta_job = _make_job(company_name="Meta")

        # Mock db — use_starred_companies=False so only the jobs query runs
        db = AsyncMock()
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [google_job, meta_job]
        db.execute = AsyncMock(return_value=jobs_result)

        matched = await find_new_jobs_for_alert(db, uuid.uuid4(), prefs, since)
        assert len(matched) == 1
        assert matched[0].company_name == "Google"

    @pytest.mark.anyio
    async def test_case_insensitive_matching(self):
        prefs = _make_prefs(watched_companies=["google"])
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        job = _make_job(company_name="Google")

        db = AsyncMock()
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [job]
        db.execute = AsyncMock(return_value=jobs_result)

        matched = await find_new_jobs_for_alert(db, uuid.uuid4(), prefs, since)
        assert len(matched) == 1

    @pytest.mark.anyio
    async def test_keyword_filter_narrows_results(self):
        prefs = _make_prefs(
            watched_companies=["Google"],
            keyword_filters=["backend"],
        )
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        backend_job = _make_job(title="Backend Engineer", company_name="Google")
        frontend_job = _make_job(title="Frontend Engineer", company_name="Google")
        # Ensure description doesn't accidentally contain "backend"
        frontend_job.description = "Work on UI components at Google"

        db = AsyncMock()
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [backend_job, frontend_job]
        db.execute = AsyncMock(return_value=jobs_result)

        matched = await find_new_jobs_for_alert(db, uuid.uuid4(), prefs, since)
        assert len(matched) == 1
        assert matched[0].title == "Backend Engineer"

    @pytest.mark.anyio
    async def test_no_watched_companies_returns_empty(self):
        prefs = _make_prefs(watched_companies=[], use_starred_companies=False)
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        db = AsyncMock()
        starred_result = MagicMock()
        starred_result.all.return_value = []
        db.execute = AsyncMock(return_value=starred_result)

        matched = await find_new_jobs_for_alert(db, uuid.uuid4(), prefs, since)
        assert matched == []

    @pytest.mark.anyio
    async def test_starred_companies_included(self):
        prefs = _make_prefs(use_starred_companies=True, watched_companies=[])
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        apple_job = _make_job(company_name="Apple")

        db = AsyncMock()
        # Starred companies query returns Apple
        starred_result = MagicMock()
        star_row = MagicMock()
        star_row.__getitem__ = lambda self, i: "Apple"
        starred_result.all.return_value = [(star_row,)]
        # Patch to return simple tuples
        starred_result.all.return_value = [("Apple",)]

        # Jobs query
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [apple_job]

        db.execute = AsyncMock(side_effect=[starred_result, jobs_result])

        matched = await find_new_jobs_for_alert(db, uuid.uuid4(), prefs, since)
        assert len(matched) == 1


# ---------------------------------------------------------------------------
# Preference model tests
# ---------------------------------------------------------------------------


class TestPreferenceModel:
    def test_default_values(self):
        # SQLAlchemy column defaults fire on INSERT, not on bare instantiation,
        # so verify the configured defaults via the column metadata directly.
        cols = JobAlertPreference.__table__.c
        assert cols.enabled.default.arg is False
        assert cols.frequency.default.arg == "daily"
        assert cols.use_starred_companies.default.arg is True
        assert cols.email_provider.default.arg == "connected"

    def test_custom_values(self):
        prefs = JobAlertPreference(
            enabled=True,
            frequency="weekly",
            watched_companies=["Google", "Meta"],
            keyword_filters=["engineer"],
        )
        assert prefs.enabled is True
        assert prefs.frequency == "weekly"
        assert prefs.watched_companies == ["Google", "Meta"]
        assert prefs.keyword_filters == ["engineer"]


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_update_schema_validates_frequency(self):
        from app.schemas.job_alerts import JobAlertPreferenceUpdate

        valid = JobAlertPreferenceUpdate(frequency="daily")
        assert valid.frequency == "daily"

        with pytest.raises(Exception):
            JobAlertPreferenceUpdate(frequency="biweekly")

    def test_update_schema_validates_provider(self):
        from app.schemas.job_alerts import JobAlertPreferenceUpdate

        valid = JobAlertPreferenceUpdate(email_provider="gmail")
        assert valid.email_provider == "gmail"

        with pytest.raises(Exception):
            JobAlertPreferenceUpdate(email_provider="yahoo")

    def test_response_schema(self):
        from app.schemas.job_alerts import JobAlertPreferenceResponse

        resp = JobAlertPreferenceResponse(
            enabled=True,
            frequency="daily",
            watched_companies=["Google"],
            use_starred_companies=True,
            keyword_filters=[],
            email_provider="connected",
            last_digest_sent_at=None,
            total_alerts_sent=5,
        )
        assert resp.total_alerts_sent == 5
        assert resp.watched_companies == ["Google"]
