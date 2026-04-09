"""Tests for connection relevance scoring and headline parsing."""

from app.utils.connection_relevance import (
    HeadlineSignals,
    generate_warm_path_reason,
    parse_headline,
    score_connection_relevance,
)
from app.utils.job_context import JobContext


# ---------------------------------------------------------------------------
# parse_headline
# ---------------------------------------------------------------------------


def test_parse_headline_engineer():
    signals = parse_headline("Software Engineer @ Robinhood")
    assert signals.role_type == "engineer"
    assert signals.department == "engineering"


def test_parse_headline_recruiter():
    signals = parse_headline("Technical Recruiter at Google")
    assert signals.role_type == "recruiter"
    assert signals.department == "human_resources"


def test_parse_headline_staff_ml():
    signals = parse_headline("Staff ML Engineer | Payments Team")
    assert signals.seniority == "staff"
    assert "ml" in signals.team_keywords
    assert signals.product_hint == "Payments Team"


def test_parse_headline_senior_backend():
    signals = parse_headline("Senior Backend Engineer at Stripe")
    assert signals.seniority == "senior"
    assert "backend" in signals.team_keywords
    assert signals.department == "engineering"


def test_parse_headline_data_scientist():
    signals = parse_headline("Data Scientist at Meta")
    assert signals.department == "data_science"
    assert signals.role_type == "engineer"


def test_parse_headline_product_manager():
    signals = parse_headline("Product Manager at Airbnb")
    assert signals.department == "product_management"
    # PM is an IC-manager role, should NOT classify as people-manager
    assert signals.role_type != "manager"


def test_parse_headline_director():
    signals = parse_headline("Director of Engineering at Netflix")
    assert signals.role_type == "manager"
    assert signals.seniority == "director"


def test_parse_headline_none():
    signals = parse_headline(None)
    assert signals.role_type == "other"
    assert signals.department is None
    assert signals.team_keywords == []
    assert signals.seniority is None
    assert signals.product_hint is None


def test_parse_headline_empty():
    signals = parse_headline("")
    assert signals.role_type == "other"


def test_parse_headline_product_hint_pipe():
    signals = parse_headline("SWE @ Google | Cloud Platform")
    assert signals.product_hint == "Cloud Platform"


def test_parse_headline_product_hint_skips_remote():
    signals = parse_headline("Engineer | Remote")
    assert signals.product_hint is None


# ---------------------------------------------------------------------------
# score_connection_relevance
# ---------------------------------------------------------------------------


def test_score_recruiter_gets_25_plus():
    ctx = JobContext(department="engineering")
    score, signals, label = score_connection_relevance(
        "Technical Recruiter at Google", "Google", ctx,
    )
    assert score >= 25
    assert label == "Recruiter"


def test_score_same_department_and_team():
    ctx = JobContext(department="engineering", team_keywords=["backend"])
    score, signals, label = score_connection_relevance(
        "Senior Backend Engineer at Stripe", "Stripe", ctx,
    )
    assert score >= 40  # 30 dept + 10 team
    assert label == "Same team"


def test_score_same_department_only():
    ctx = JobContext(department="engineering", team_keywords=["ml"])
    score, signals, label = score_connection_relevance(
        "Frontend Engineer at Meta", "Meta", ctx,
    )
    assert score >= 30
    assert label == "Same department"


def test_score_different_department():
    ctx = JobContext(department="engineering")
    score, signals, label = score_connection_relevance(
        "Marketing Manager at Google", "Google", ctx,
    )
    assert score < 20


def test_score_no_headline():
    ctx = JobContext(department="engineering")
    score, signals, label = score_connection_relevance(None, "Google", ctx)
    assert score == 5
    assert label == "At Google"


def test_score_seniority_proximity():
    ctx = JobContext(department="engineering", seniority="senior")
    score_close, _, _ = score_connection_relevance(
        "Senior Engineer at Acme", "Acme", ctx,
    )
    score_far, _, _ = score_connection_relevance(
        "Intern at Acme", "Acme", ctx,
    )
    # Both match department (30) but seniority should differ
    assert score_close > score_far


def test_score_product_match():
    ctx = JobContext(
        department="engineering",
        product_team_names=["Cloud Platform"],
    )
    score, _, label = score_connection_relevance(
        "SWE @ Google | Cloud Platform", "Google", ctx,
    )
    assert score >= 45  # 30 dept + 15 product
    assert "team" in label.lower() or "product" in label.lower() or "department" in label.lower()


# ---------------------------------------------------------------------------
# generate_warm_path_reason
# ---------------------------------------------------------------------------


def test_reason_direct_recruiter():
    signals = HeadlineSignals(role_type="recruiter")
    ctx = JobContext(department="engineering")
    reason = generate_warm_path_reason(
        "Alice", "Recruiter at Google", signals, "Google", ctx, is_direct=True,
    )
    assert "Alice" in reason
    assert "Recruiter" in reason


def test_reason_direct_same_team():
    signals = HeadlineSignals(
        role_type="engineer",
        department="engineering",
        team_keywords=["backend"],
    )
    ctx = JobContext(department="engineering", team_keywords=["backend"])
    reason = generate_warm_path_reason(
        "Bob", "Senior Backend Engineer", signals, "Acme", ctx, is_direct=True,
    )
    assert "Bob" in reason
    assert "same team" in reason.lower()


def test_reason_bridge_generic():
    signals = HeadlineSignals(role_type="other")
    reason = generate_warm_path_reason(
        "Carol", "Office Manager", signals, "Acme", None, is_direct=False,
    )
    assert "Carol" in reason
    assert "Acme" in reason


def test_reason_direct_no_context():
    signals = HeadlineSignals()
    reason = generate_warm_path_reason(
        "Dave", None, signals, "Acme", None, is_direct=True,
    )
    assert "Dave" in reason
    assert "connected" in reason.lower()
