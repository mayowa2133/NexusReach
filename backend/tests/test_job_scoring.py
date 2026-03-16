"""Tests for job scoring and deduplication — Phase 6.

Tests pure functions from job_service.py: _score_job and _fingerprint.
No database or external API calls needed.
"""

from unittest.mock import MagicMock

from app.services.job_service import _score_job, _fingerprint


def _make_profile(**overrides):
    """Create a mock Profile object for scoring tests."""
    profile = MagicMock()
    profile.target_roles = overrides.get("target_roles", ["Software Engineer"])
    profile.target_industries = overrides.get("target_industries", ["Technology"])
    profile.target_locations = overrides.get("target_locations", ["New York"])
    profile.resume_parsed = overrides.get("resume_parsed", {
        "skills": ["Python", "React", "TypeScript", "FastAPI", "PostgreSQL"],
    })
    return profile


def _make_job(**overrides):
    """Create a job data dict for scoring tests."""
    defaults = {
        "title": "Software Engineer",
        "description": "Build web apps with Python and React",
        "company_name": "TechCorp",
        "location": "New York, NY",
        "remote": False,
    }
    defaults.update(overrides)
    return defaults


# --- _score_job ---


class TestScoreJob:
    def test_no_profile_returns_zero(self):
        score, breakdown = _score_job(_make_job(), None)
        assert score == 0.0
        assert breakdown == {}

    def test_full_profile_high_score(self):
        """A job matching role, skills, industry, and location should score high."""
        profile = _make_profile()
        job = _make_job(
            title="Software Engineer",
            description="Build web apps with Python and React at a Technology company",
            location="New York, NY",
        )
        score, breakdown = _score_job(job, profile)
        assert score > 50.0
        assert breakdown["role_match"] == 30.0  # exact title match

    def test_role_match_in_title(self):
        profile = _make_profile(target_roles=["Backend Developer"])
        job = _make_job(title="Backend Developer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["role_match"] == 30.0

    def test_role_match_in_description_only(self):
        profile = _make_profile(target_roles=["Backend Developer"])
        job = _make_job(title="Engineer", description="Looking for a backend developer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["role_match"] == 15.0

    def test_no_role_match(self):
        profile = _make_profile(target_roles=["Data Scientist"])
        job = _make_job(title="Frontend Designer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["role_match"] == 0.0

    def test_skills_match(self):
        profile = _make_profile(
            resume_parsed={"skills": ["Python", "React", "Node.js", "Docker"]}
        )
        job = _make_job(description="We use Python, React, and Docker")
        _, breakdown = _score_job(job, profile)
        assert breakdown["skills_match"] > 0

    def test_no_skills_in_profile(self):
        profile = _make_profile(resume_parsed={"skills": []})
        _, breakdown = _score_job(_make_job(), profile)
        assert breakdown["skills_match"] == 0.0

    def test_no_resume_parsed(self):
        profile = _make_profile(resume_parsed=None)
        _, breakdown = _score_job(_make_job(), profile)
        assert breakdown["skills_match"] == 0.0

    def test_industry_match_in_description(self):
        profile = _make_profile(target_industries=["Fintech"])
        job = _make_job(description="Join our fintech team")
        _, breakdown = _score_job(job, profile)
        assert breakdown["industry_match"] == 15.0

    def test_industry_match_in_company_name(self):
        profile = _make_profile(target_industries=["AI"])
        job = _make_job(company_name="AI Startup Inc")
        _, breakdown = _score_job(job, profile)
        assert breakdown["industry_match"] == 15.0

    def test_location_match(self):
        profile = _make_profile(target_locations=["San Francisco"])
        job = _make_job(location="San Francisco, CA")
        _, breakdown = _score_job(job, profile)
        assert breakdown["location_match"] == 15.0

    def test_remote_location_bonus(self):
        profile = _make_profile(target_locations=["New York"])
        job = _make_job(location="Austin, TX", remote=True)
        _, breakdown = _score_job(job, profile)
        assert breakdown["location_match"] == 10.0  # remote bonus

    def test_remote_no_target_locations(self):
        profile = _make_profile(target_locations=None)
        job = _make_job(remote=True)
        _, breakdown = _score_job(job, profile)
        assert breakdown["location_match"] == 10.0

    def test_level_fit_junior(self):
        profile = _make_profile()
        job = _make_job(title="Junior Software Engineer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["level_fit"] == 10.0

    def test_level_fit_senior(self):
        profile = _make_profile()
        job = _make_job(title="Senior Staff Engineer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["level_fit"] == 2.0

    def test_level_fit_mid(self):
        profile = _make_profile()
        job = _make_job(title="Software Engineer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["level_fit"] == 5.0

    def test_score_is_sum_of_breakdown(self):
        profile = _make_profile()
        job = _make_job()
        score, breakdown = _score_job(job, profile)
        assert score == round(sum(breakdown.values()), 1)

    def test_score_range(self):
        """Score should always be between 0 and 100."""
        profile = _make_profile()
        job = _make_job()
        score, _ = _score_job(job, profile)
        assert 0 <= score <= 100


# --- _fingerprint ---


class TestFingerprint:
    def test_same_input_same_hash(self):
        fp1 = _fingerprint("Acme Corp", "Engineer", "NYC")
        fp2 = _fingerprint("Acme Corp", "Engineer", "NYC")
        assert fp1 == fp2

    def test_case_insensitive(self):
        fp1 = _fingerprint("Acme Corp", "Software Engineer", "New York")
        fp2 = _fingerprint("acme corp", "software engineer", "new york")
        assert fp1 == fp2

    def test_whitespace_handling(self):
        fp1 = _fingerprint(" Acme Corp ", " Engineer ", " NYC ")
        fp2 = _fingerprint("Acme Corp", "Engineer", "NYC")
        assert fp1 == fp2

    def test_different_jobs_different_hash(self):
        fp1 = _fingerprint("Acme", "Engineer", "NYC")
        fp2 = _fingerprint("Acme", "Designer", "NYC")
        assert fp1 != fp2

    def test_returns_hex_string(self):
        fp = _fingerprint("Company", "Title", "Location")
        assert isinstance(fp, str)
        assert len(fp) == 32  # MD5 hex
