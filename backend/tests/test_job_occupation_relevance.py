"""Occupation-targeted ingestion must reject query noise before persistence."""

from app.services.jobs.search import _occupation_relevance, _record_accepted_job_quality
from app.services.jobs.storage import _infer_occupation_tags_for_job
from app.services.occupation_taxonomy import decide_job_occupation_relevance


def test_targeted_job_accepts_matching_content_classification():
    accepted, reason, keys = _occupation_relevance(
        {
            "title": "Associate II",
            "description": "Run brand campaigns, content strategy, SEO, and paid media.",
        },
        "marketing",
    )
    assert accepted is True
    assert reason == "content_classification"
    assert "marketing" in keys


def test_targeted_job_rejects_classified_off_category_result():
    accepted, reason, keys = _occupation_relevance(
        {"title": "Senior Software Engineer", "description": "Build APIs."},
        "marketing",
    )
    assert accepted is False
    assert reason == "off_category"
    assert "software_engineering" in keys


def test_targeted_job_rejects_unclassified_query_hint():
    accepted, reason, keys = _occupation_relevance(
        {"title": "Associate II", "description": "Join our growing team."},
        "sales",
    )
    assert (accepted, reason, keys) == (False, "unclassified", [])


def test_trusted_explicit_source_category_can_accept_generic_title():
    accepted, reason, keys = _occupation_relevance(
        {
            "title": "Associate II",
            "description": "Join our growing team.",
            "tags": ["occupation:healthcare"],
        },
        "healthcare",
    )
    assert accepted is True
    assert reason == "explicit_source_tag"
    assert keys == ["healthcare"]


def test_invalid_requested_occupation_fails_closed():
    assert _occupation_relevance(
        {"title": "Software Engineer"}, "removed_taxonomy_key"
    ) == (False, "invalid_requested_occupation", [])


def test_occupation_classification_persists_confidence_and_provenance():
    data = {
        "title": "Associate II",
        "description": "Provide patient care as a registered nurse.",
        "tags": [],
    }

    _infer_occupation_tags_for_job(data)

    assert "occupation:healthcare" in data["tags"]
    classification = data["metadata_provenance"]["occupation_classification"]
    assert classification["version"] == 2
    assert classification["keys"] == ["healthcare"]
    assert classification["source"] == "description_classifier"
    assert classification["confidence"] == 0.75
    assert classification["evidence"] == ["description_lead"]
    assert classification["query_hint"] is None


def test_query_hint_is_provenance_but_never_targeted_relevance_evidence():
    decision = decide_job_occupation_relevance(
        title="Associate II",
        description="Join our growing team.",
        requested_keys=["marketing"],
        query_hint="marketing",
    )

    assert decision.accepted is False
    assert decision.reason == "unclassified"
    assert decision.inference.source == "query_hint"
    assert decision.inference.keys == ("marketing",)
    assert decision.inference.confidence == 0.25


def test_multi_occupation_relevance_accepts_any_independent_match():
    decision = decide_job_occupation_relevance(
        title="Financial Analyst",
        description="Build forecasts and budgets.",
        requested_keys=["marketing", "accounting_finance"],
    )

    assert decision.accepted is True
    assert decision.requested_keys == ("marketing", "accounting_finance")
    assert decision.inference.keys == ("accounting_finance",)


def test_source_quality_stats_measure_accepted_metadata_yield():
    stat = {"details": None}
    _record_accepted_job_quality(stat, {
        "description": "Role description",
        "apply_url": "https://employer.example/jobs/1",
        "posted_at": "2026-07-12",
        "salary_min": 90000,
        "location": "Toronto, ON",
    })
    _record_accepted_job_quality(stat, {"description": "Another role"})

    assert stat["details"] == {
        "accepted_count": 2,
        "with_description": 2,
        "with_direct_apply": 1,
        "with_posted_date": 1,
        "with_salary": 1,
        "with_location": 1,
    }
