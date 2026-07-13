"""Tests for job scoring and deduplication.

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
    profile.target_occupations = overrides.get("target_occupations", [])
    profile.resume_parsed = overrides.get("resume_parsed", {
        "skills": ["Python", "React", "TypeScript", "FastAPI", "PostgreSQL"],
        "experience": [
            {"title": "Software Engineer", "company": "OldCo", "description": "Built APIs"},
        ],
        "education": [
            {"degree": "BS", "field": "Computer Science", "institution": "State U"},
        ],
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
        assert score is None
        assert breakdown.get("resume_missing") is True
        assert breakdown.get("resume_not_uploaded") is True

    def test_full_profile_high_score(self):
        """A job matching role, skills, and location should score high."""
        profile = _make_profile()
        job = _make_job(
            title="Software Engineer",
            description="Build web apps with Python and React at a Technology company",
            location="New York, NY",
        )
        score, breakdown = _score_job(job, profile)
        assert score > 40.0
        assert breakdown["role_match"] > 0

    def test_role_match_in_title(self):
        profile = _make_profile(target_roles=["Backend Developer"])
        job = _make_job(title="Backend Developer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["role_match"] == 20.0  # full role match (20 points max)

    def test_role_match_in_description_only(self):
        profile = _make_profile(target_roles=["Backend Developer"])
        job = _make_job(title="Engineer", description="Looking for a backend developer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["role_match"] == 10.0  # description-only = half

    def test_no_role_match(self):
        profile = _make_profile(target_roles=["Data Scientist"])
        job = _make_job(title="Frontend Designer", description="Design pixel-perfect UIs")
        _, breakdown = _score_job(job, profile)
        assert breakdown["role_match"] == 0.0

    def test_skills_match(self):
        profile = _make_profile(
            resume_parsed={
                "skills": ["Python", "React", "Node.js", "Docker"],
                "experience": [],
                "education": [],
            }
        )
        job = _make_job(description="We use Python, React, and Docker")
        _, breakdown = _score_job(job, profile)
        assert breakdown["skills_match"] > 0

    def test_no_skills_in_profile(self):
        profile = _make_profile(
            resume_parsed={"skills": [], "experience": [], "education": []}
        )
        _, breakdown = _score_job(_make_job(), profile)
        assert breakdown["skills_match"] == 0.0

    def test_no_resume_parsed(self):
        profile = _make_profile(resume_parsed=None)
        score, breakdown = _score_job(_make_job(), profile)
        assert score is None
        assert breakdown["resume_missing"] is True

    def test_location_match(self):
        profile = _make_profile(target_locations=["San Francisco"])
        job = _make_job(location="San Francisco, CA")
        _, breakdown = _score_job(job, profile)
        assert breakdown["location_match"] == 10.0  # full location match (10 points max)

    def test_remote_location_bonus(self):
        profile = _make_profile(target_locations=["New York"])
        job = _make_job(location="Austin, TX", remote=True)
        _, breakdown = _score_job(job, profile)
        assert breakdown["location_match"] == 8.0  # remote bonus = 80% of max

    def test_remote_no_target_locations(self):
        profile = _make_profile(target_locations=None)
        job = _make_job(remote=True)
        _, breakdown = _score_job(job, profile)
        assert breakdown["location_match"] == 7.0  # remote, no prefs = 70% of max

    def test_level_fit_default(self):
        profile = _make_profile()
        job = _make_job(title="Software Engineer")
        _, breakdown = _score_job(job, profile)
        assert breakdown["level_fit"] == 2.5  # default = half of 5

    def test_experience_match(self):
        profile = _make_profile()
        job = _make_job(title="Software Engineer", description="Build APIs with Python")
        _, breakdown = _score_job(job, profile)
        assert breakdown["experience_match"] > 0

    def test_education_match(self):
        profile = _make_profile()
        job = _make_job(description="Requires Computer Science degree")
        _, breakdown = _score_job(job, profile)
        assert breakdown["education_match"] > 0

    def test_score_numeric_keys_sum(self):
        """Numeric breakdown keys should sum to the total score."""
        profile = _make_profile()
        job = _make_job()
        score, breakdown = _score_job(job, profile)
        numeric_keys = [
            "skills_match", "experience_match", "role_match",
            "location_match", "education_match", "level_fit",
        ]
        computed_sum = sum(breakdown[k] for k in numeric_keys if k in breakdown)
        assert score == round(computed_sum, 1)

    def test_score_range(self):
        """Score should always be between 0 and 100."""
        profile = _make_profile()
        job = _make_job()
        score, _ = _score_job(job, profile)
        assert score is not None
        assert 0 <= score <= 100

    def test_breakdown_has_category_maxes(self):
        """Breakdown should include category_maxes for frontend display."""
        profile = _make_profile()
        job = _make_job()
        _, breakdown = _score_job(job, profile)
        assert "category_maxes" in breakdown
        maxes = breakdown["category_maxes"]
        assert maxes["skills_match"] == 35
        assert maxes["experience_match"] == 25
        assert maxes["role_match"] == 20
        assert maxes["location_match"] == 10

    def test_skills_detail_in_breakdown(self):
        """Breakdown should include matched skills detail."""
        profile = _make_profile()
        job = _make_job(description="We use Python and React daily")
        _, breakdown = _score_job(job, profile)
        detail = breakdown.get("skills_detail", {})
        assert "matched" in detail
        assert isinstance(detail["matched"], list)

    def test_required_skill_detail_and_resume_duration(self):
        profile = _make_profile(
            resume_parsed={
                "skills": ["Python", "React"],
                "experience": [
                    {
                        "title": "Software Engineer",
                        "company": "OldCo",
                        "start_date": "2020-01",
                        "end_date": "2024-12",
                        "description": "Built APIs",
                    },
                ],
                "education": [],
            }
        )
        job = _make_job(
            description="Requirements\n5+ years of experience. Python and React required.",
            experience_level="senior",
        )

        _, breakdown = _score_job(job, profile)

        assert "python" in breakdown["skills_detail"]["required_matched"]
        assert breakdown["level_detail"]["user_years"] >= 5
        assert breakdown["level_fit"] == 5.0

    def test_skill_synonym_matching(self):
        """Skills with synonyms should match (e.g., 'JS' matches 'javascript')."""
        profile = _make_profile(
            resume_parsed={
                "skills": ["JavaScript"],
                "experience": [],
                "education": [],
            }
        )
        job = _make_job(description="Experience with JS and Node.js required")
        _, breakdown = _score_job(job, profile)
        assert breakdown["skills_match"] > 0

    def test_word_boundary_skill_matching(self):
        """Short skills like 'R' should use word boundaries, not substring."""
        profile = _make_profile(
            resume_parsed={
                "skills": ["R"],
                "experience": [],
                "education": [],
            }
        )
        # "React" contains "R" but shouldn't match with word boundary
        job = _make_job(description="We use React and TypeScript")
        _, breakdown = _score_job(job, profile)
        detail = breakdown.get("skills_detail", {})
        matched = detail.get("matched", [])
        assert "rlang" not in matched

    def test_extra_resume_skills_do_not_reduce_job_requirement_coverage(self):
        base_resume = {
            "skills": ["Python"],
            "experience": [{
                "title": "Software Engineer",
                "company": "Acme",
                "description": "Built Python APIs",
            }],
            "education": [],
        }
        broad_resume = {
            **base_resume,
            "skills": [
                "Python", "Excel", "Figma", "Salesforce", "Tableau",
                "Copywriting", "Budgeting", "Recruiting",
            ],
        }
        job = _make_job(description="Python API development required")

        _, narrow = _score_job(job, _make_profile(resume_parsed=base_resume))
        _, broad = _score_job(job, _make_profile(resume_parsed=broad_resume))

        assert broad["skills_match"] == narrow["skills_match"]

    def test_nontechnical_occupation_and_experience_receive_first_class_credit(self):
        profile = _make_profile(
            target_roles=[],
            target_occupations=["accounting_finance"],
            resume_parsed={
                "skills": ["Forecasting", "Budgeting", "Variance Analysis"],
                "experience": [{
                    "title": "FP&A Analyst",
                    "company": "Acme",
                    "description": "Owned forecasts, budgets, and variance analysis.",
                }],
                "education": [],
            },
        )
        job = _make_job(
            title="Financial Analyst",
            description="Own forecasts, budgets, and variance analysis.",
        )

        _, breakdown = _score_job(job, profile)

        assert breakdown["role_match"] == 20.0
        assert breakdown["experience_match"] > 0
        assert breakdown["skills_match"] > 0

    def test_missing_required_credential_is_explicit_and_penalized(self):
        job = _make_job(
            title="Senior Accountant",
            description="Requirements\nCPA required. Own financial reporting and audit.",
        )
        missing_profile = _make_profile(
            target_roles=["Senior Accountant"],
            resume_parsed={
                "skills": ["Financial Reporting", "Audit"],
                "experience": [],
                "education": [],
            },
        )
        qualified_profile = _make_profile(
            target_roles=["Senior Accountant"],
            resume_parsed={
                "skills": ["Financial Reporting", "Audit", "CPA"],
                "experience": [],
                "education": [],
            },
        )

        missing_score, missing = _score_job(job, missing_profile)
        qualified_score, qualified = _score_job(job, qualified_profile)

        assert missing["critical_constraints"]["missing"] == ["CPA"]
        assert missing["critical_constraints"]["penalty"] == 10.0
        assert qualified["critical_constraints"]["missing"] == []
        assert qualified_score > missing_score


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

    def test_company_suffix_and_title_punctuation_variants_cluster(self):
        fp1 = _fingerprint("Acme, Inc.", "Sr. FP&A Analyst", "Toronto, ON")
        fp2 = _fingerprint("ACME", "Senior FP&A Analyst", "Toronto, ON")
        assert fp1 == fp2

    def test_remote_location_variants_cluster(self):
        fp1 = _fingerprint("Acme", "Marketing Manager (Remote)", "Remote - Canada")
        fp2 = _fingerprint("Acme Corp", "Marketing Manager", "Remote")
        assert fp1 == fp2

    def test_returns_hex_string(self):
        fp = _fingerprint("Company", "Title", "Location")
        assert isinstance(fp, str)
        assert len(fp) == 32  # MD5 hex
