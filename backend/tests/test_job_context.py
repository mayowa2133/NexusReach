"""Unit tests for job context extraction utility."""

from app.utils.job_context import extract_job_context


def test_backend_engineer():
    ctx = extract_job_context("Backend Engineer")
    assert ctx.department == "engineering"
    assert "backend" in ctx.team_keywords
    assert ctx.seniority == "mid"
    assert any("Backend" in t for t in ctx.peer_titles)
    assert any("Manager" in t for t in ctx.manager_titles)


def test_senior_backend_engineer():
    ctx = extract_job_context("Senior Backend Engineer")
    assert ctx.department == "engineering"
    assert "backend" in ctx.team_keywords
    assert ctx.seniority == "senior"
    # Peer titles should include senior variants
    assert any("Senior" in t for t in ctx.peer_titles)


def test_senior_product_manager():
    ctx = extract_job_context("Senior Product Manager")
    assert ctx.department == "product_management"
    assert ctx.seniority == "senior"
    assert "product_management" in ctx.apollo_departments


def test_ml_engineer():
    ctx = extract_job_context("ML Engineer")
    assert ctx.department == "data_science"
    assert "ml" in ctx.team_keywords
    assert "engineering_technical" in ctx.apollo_departments or "data" in ctx.apollo_departments


def test_junior_frontend_developer():
    ctx = extract_job_context("Junior Frontend Developer")
    assert ctx.department == "engineering"
    assert "frontend" in ctx.team_keywords
    assert ctx.seniority == "junior"


def test_generic_software_engineer():
    """Generic title still produces usable context with broad fallback."""
    ctx = extract_job_context("Software Engineer")
    assert ctx.department == "engineering"
    assert ctx.seniority == "mid"
    assert len(ctx.peer_titles) > 0
    assert len(ctx.manager_titles) > 0
    assert len(ctx.recruiter_titles) > 0


def test_staff_sre():
    ctx = extract_job_context("Staff Site Reliability Engineer")
    assert ctx.department == "engineering"
    assert ctx.seniority == "staff"
    assert "devops" in ctx.team_keywords


def test_data_scientist():
    ctx = extract_job_context("Data Scientist")
    assert ctx.department == "data_science"
    assert any("data" in kw for kw in ctx.team_keywords) or ctx.department == "data_science"


def test_html_description_stripping():
    """HTML tags in descriptions should be stripped before keyword extraction."""
    ctx = extract_job_context(
        "Software Engineer",
        description="<p>We're building a <strong>backend</strong> platform.</p>",
    )
    assert "backend" in ctx.team_keywords or "platform" in ctx.team_keywords


def test_description_enriches_team_keywords():
    """Description can provide team keywords even when title is generic."""
    ctx = extract_job_context(
        "Software Engineer",
        description="Join our machine learning infrastructure team building ML pipelines.",
    )
    assert "ml" in ctx.team_keywords


def test_recruiter_titles_always_present():
    ctx = extract_job_context("Backend Engineer")
    assert len(ctx.recruiter_titles) >= 2
    assert any("recruiter" in t.lower() for t in ctx.recruiter_titles)


def test_apollo_departments_mapped():
    ctx = extract_job_context("Marketing Manager")
    assert ctx.department == "marketing"
    assert "marketing" in ctx.apollo_departments


def test_director_seniority():
    ctx = extract_job_context("Director of Engineering")
    assert ctx.seniority == "director"


def test_intern_seniority():
    ctx = extract_job_context("Software Engineering Intern")
    assert ctx.seniority == "intern"


def test_credit_decisioning_keeps_high_signal_keywords():
    ctx = extract_job_context(
        "Software Engineer II, Backend (Credit Decisioning)",
        description=(
            "Build backend APIs for our credit decisioning platform. "
            "Partner with risk teams and own decision engine reliability. "
            "You will not work on frontend or growth surfaces."
        ),
    )
    assert "backend" in ctx.team_keywords
    assert "credit" in ctx.team_keywords
    assert "decisioning" in ctx.team_keywords
    assert "frontend" not in ctx.team_keywords
    assert "growth" not in ctx.team_keywords


def test_marketplace_performance_extracts_domain_context():
    ctx = extract_job_context(
        "Software Engineer, Backend (Marketplace Performance)",
        description=(
            "Join the marketplace team focused on search, discovery, deals, and merchant details. "
            "Build backend services and APIs that improve the consumer experience."
        ),
    )
    assert "backend" in ctx.team_keywords
    assert "marketplace" in ctx.team_keywords
    assert any(keyword in ctx.team_keywords for keyword in ("merchant", "consumer"))
