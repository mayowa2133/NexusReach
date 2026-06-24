from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.resume_artifact.quality import (
    EARLY_CAREER_TECHNICAL,
    EXPERIENCED_TECHNICAL,
    GENERAL_PROFESSIONAL,
    _job_terms,
    _term_present,
    evaluate_resume_quality,
    select_quality_profile,
    validate_quality_evaluation,
)


def _technical_resume() -> dict:
    return {
        "contact": {
            "email": "candidate@example.com",
            "urls": ["https://github.com/candidate"],
        },
        "experience": [
            {
                "title": "Software Engineering Intern",
                "company": "Acme",
                "start_date": "May 2025",
                "end_date": "Aug 2025",
                "bullets": [
                    "Shipped a production Python API used by 500 customers and reduced latency by 25%.",
                    "Added monitoring and automated tests for reliable releases.",
                ],
            }
        ],
        "projects": [
            {
                "name": "SignalFlow",
                "url": "https://github.com/candidate/signalflow",
                "technologies": ["Python", "React", "PostgreSQL"],
                "bullets": [
                    "Built a full-stack real-time workflow with authentication, a database, and 120 tests.",
                    "Deployed an API and React interface for 40 beta users.",
                ],
            }
        ],
        "skills": ["Python", "React", "PostgreSQL", "Testing"],
    }


def _technical_job(title: str = "Software Engineer Intern") -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        company_name="Target",
        description=(
            "Build Python and React services. Python experience and React testing "
            "are required for this software engineering role."
        ),
        experience_level="intern" if "Intern" in title else "senior",
        department="engineering",
        tags=["occupation:software_engineering"],
    )


def _technical_content() -> str:
    return r"""
\documentclass{article}
\begin{document}
candidate@example.com \url{https://github.com/candidate}
\subsection*{Experience}
Acme — Software Engineering Intern
\item Shipped a production Python API used by 500 customers and reduced latency by 25%.
\item Added monitoring and automated tests for reliable releases.
\subsection*{Projects}
SignalFlow \href{https://github.com/candidate/signalflow}{GitHub}
\item Built a full-stack real-time workflow with authentication, a database, and 120 tests.
\item Deployed an API and React interface for 40 beta users.
\subsection*{Technical Skills}
Python, React, PostgreSQL, Testing
\subsection*{Education}
Bachelor of Science
\end{document}
"""


def test_early_career_profile_preserves_published_hackerrank_category_balance():
    profile = select_quality_profile(_technical_resume(), _technical_job())

    assert profile is EARLY_CAREER_TECHNICAL
    assert [(category.key, category.maximum) for category in profile.categories] == [
        ("open_source", 35),
        ("projects", 30),
        ("production", 25),
        ("technical_skills", 10),
    ]


def test_profile_selection_is_occupation_and_seniority_aware():
    senior = select_quality_profile(
        _technical_resume(),
        _technical_job("Senior Software Engineer"),
    )
    nontechnical = select_quality_profile(
        _technical_resume(),
        SimpleNamespace(
            title="Account Executive",
            description="Own enterprise sales and customer relationships.",
            experience_level="senior",
            department="sales",
            tags=["occupation:sales"],
        ),
    )

    assert senior is EXPERIENCED_TECHNICAL
    assert nontechnical is GENERAL_PROFESSIONAL
    assert all(category.key != "open_source" for category in nontechnical.categories)


def test_personal_github_is_not_misrepresented_as_open_source_contribution():
    evaluation = evaluate_resume_quality(
        parsed=_technical_resume(),
        content=_technical_content(),
        job=_technical_job(),
    )

    open_source = next(
        category for category in evaluation["categories"]
        if category["key"] == "open_source"
    )
    assert open_source["score"] == 5.0
    assert "not treated as third-party contributions" in open_source["evidence"][0]


def test_generic_contributed_to_wording_is_not_open_source_evidence():
    parsed = _technical_resume()
    generic = "Contributed to the design and implementation of a customer-facing feature."
    parsed["experience"][0]["bullets"].append(generic)
    content = _technical_content().replace(
        r"\subsection*{Projects}",
        f"\\item {generic}\n\\subsection*{{Projects}}",
    )

    evaluation = evaluate_resume_quality(
        parsed=parsed,
        content=content,
        job=_technical_job(),
    )
    open_source = next(
        category for category in evaluation["categories"]
        if category["key"] == "open_source"
    )

    assert open_source["score"] == 5.0


def test_explicit_technical_requirements_take_priority_over_job_boilerplate():
    job = SimpleNamespace(
        title="Developer Intern, Service Development - Fall 2026",
        description=(
            "Our team and every team across the company work together. " * 10
            + "Build backend services with Go, REST, gRPC, Agile code reviews, and CI/CD."
        ),
    )

    terms = _job_terms(job)

    assert terms == ["backend", "Go", "REST", "gRPC", "Agile", "code reviews", "CI/CD"]
    assert "team" not in terms


def test_short_skill_terms_require_token_boundaries():
    assert _term_present("Built production Go services", "Go") is True
    assert _term_present("Built a goal-based algorithm", "Go") is False
    assert _term_present("Improved ongoing delivery", "Go") is False
    assert _term_present("Designed RESTful APIs", "REST") is True


def test_supported_production_project_and_skill_evidence_improves_over_sparse_resume():
    rich = evaluate_resume_quality(
        parsed=_technical_resume(),
        content=_technical_content(),
        job=_technical_job(),
    )
    sparse = evaluate_resume_quality(
        parsed={"contact": {"email": "candidate@example.com"}},
        content="candidate@example.com",
        job=_technical_job(),
    )

    assert rich["overall_score"] > sparse["overall_score"]
    assert rich["axes"]["evidence_quality"]["score"] > sparse["axes"]["evidence_quality"]["score"]
    assert rich["axes"]["parseability"]["score"] > sparse["axes"]["parseability"]["score"]


def test_explicit_open_source_evidence_scores_above_personal_repository_only():
    parsed = _technical_resume()
    contribution = (
        "Contributed to the Kubernetes open-source project through 3 merged pull requests."
    )
    parsed["projects"][0]["bullets"].append(contribution)
    content = _technical_content().replace(
        r"\subsection*{Technical Skills}",
        rf"\item {contribution}\n\subsection*{{Technical Skills}}",
    )

    evaluation = evaluate_resume_quality(
        parsed=parsed,
        content=content,
        job=_technical_job(),
    )
    open_source = next(
        category for category in evaluation["categories"]
        if category["key"] == "open_source"
    )

    assert open_source["score"] > 3
    assert "explicit third-party/open-source" in open_source["evidence"][0]


def test_unrelated_header_url_does_not_make_an_unlinked_project_look_verified():
    parsed = _technical_resume()
    parsed["projects"][0].pop("url")
    content = _technical_content().replace(
        r"SignalFlow \href{https://github.com/candidate/signalflow}{GitHub}",
        "SignalFlow",
    )

    evaluation = evaluate_resume_quality(
        parsed=parsed,
        content=content,
        job=_technical_job(),
    )
    projects = next(
        category for category in evaluation["categories"]
        if category["key"] == "projects"
    )

    assert "0 include a repository or demo reference" in projects["evidence"][0]


def test_unconfirmed_inferred_claims_are_excluded_from_scoring():
    job = _technical_job()
    job.description = "Build Kubernetes services. Kubernetes expertise is required."
    content = _technical_content().replace(
        "Python, React, PostgreSQL, Testing",
        "Python, React, PostgreSQL, Testing, Kubernetes",
    )
    rewrites = [
        {
            "id": "rw-k8s",
            "change_type": "inferred_claim",
            "inferred_additions": ["Kubernetes"],
        }
    ]

    pending = evaluate_resume_quality(
        parsed=_technical_resume(),
        content=content,
        job=job,
        rewrites=rewrites,
        rewrite_decisions={"rw-k8s": "pending"},
    )
    confirmed = evaluate_resume_quality(
        parsed=_technical_resume(),
        content=content,
        job=job,
        rewrites=rewrites,
        rewrite_decisions={"rw-k8s": "accepted"},
    )

    assert pending["truthfulness"]["unverified_inferred_additions_excluded"] == 1
    assert pending["axes"]["job_fit"]["score"] < confirmed["axes"]["job_fit"]["score"]


def test_unsupported_skill_keyword_cannot_game_job_fit():
    job = _technical_job()
    job.description = "Build Kubernetes services. Kubernetes expertise is required."
    baseline = evaluate_resume_quality(
        parsed=_technical_resume(),
        content=_technical_content(),
        job=job,
    )
    keyword_stuffed = evaluate_resume_quality(
        parsed=_technical_resume(),
        content=_technical_content().replace(
            "Python, React, PostgreSQL, Testing",
            "Python, React, PostgreSQL, Testing, Kubernetes",
        ),
        job=job,
    )

    assert keyword_stuffed["axes"]["job_fit"]["score"] == baseline["axes"]["job_fit"]["score"]
    assert "do not add without evidence" in keyword_stuffed["axes"]["job_fit"]["improvements"][0]


@pytest.mark.parametrize(
    "job",
    [
        _technical_job(),
        _technical_job("Senior Software Engineer"),
        SimpleNamespace(
            title="Sales Manager",
            description="Lead sales strategy and customer growth. Sales leadership required.",
            experience_level="senior",
            department="sales",
            tags=["occupation:sales"],
        ),
    ],
)
def test_evaluation_is_repeatable_and_every_score_is_bounded(job):
    first = evaluate_resume_quality(
        parsed=_technical_resume(),
        content=_technical_content(),
        job=job,
    )
    second = evaluate_resume_quality(
        parsed=deepcopy(_technical_resume()),
        content=_technical_content(),
        job=job,
    )

    validate_quality_evaluation(first)
    assert first["overall_score"] == second["overall_score"]
    assert first["axes"] == second["axes"]
    assert first["categories"] == second["categories"]
    assert 0 <= first["overall_score"] <= 100
    for category in first["categories"]:
        assert 0 <= category["score"] <= category["max"]


def test_fairness_excludes_school_name_grades_and_location_from_score():
    baseline = _technical_resume()
    changed = deepcopy(baseline)
    baseline["education"] = [{"institution": "School A", "details": ["GPA 2.1"]}]
    changed["education"] = [{"institution": "Famous School", "details": ["GPA 4.0"]}]
    changed["contact"]["location"] = "Different Country"

    first = evaluate_resume_quality(
        parsed=baseline,
        content=_technical_content(),
        job=_technical_job(),
    )
    second = evaluate_resume_quality(
        parsed=changed,
        content=_technical_content(),
        job=_technical_job(),
    )

    assert first["overall_score"] == second["overall_score"]
    assert first["categories"] == second["categories"]


@pytest.mark.parametrize(
    "parsed,content",
    [
        ({}, ""),
        ({"experience": "not-a-list", "projects": [None, "bad"]}, "plain text"),
        ({"skills": [None, 42], "skills_by_category": {"Tools": "Python"}}, "Skills"),
        ({"contact": {"urls": [None]}, "experience": [{}], "projects": [{}]}, r"\documentclass{article}"),
    ],
)
def test_malformed_or_sparse_resume_data_fails_soft_with_bounded_scores(parsed, content):
    evaluation = evaluate_resume_quality(
        parsed=parsed,
        content=content,
        job=SimpleNamespace(title="Unknown Role", description="", tags=[]),
    )

    validate_quality_evaluation(evaluation)
    assert evaluation["status"] == "ready"
    assert 0 <= evaluation["overall_score"] <= 100
