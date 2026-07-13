from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.resume_artifact.quality import (
    EARLY_CAREER_TECHNICAL,
    EXPERIENCED_TECHNICAL,
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
    assert nontechnical.key == "sales_professional_v1"
    assert nontechnical.label == "Sales professional"
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


# ---------------------------------------------------------------------------
# Non-technical job coverage (2026-07 category-accuracy pass)
# ---------------------------------------------------------------------------

def _general_job(title: str, description: str, tags: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        title=title,
        company_name="Co",
        description=description,
        experience_level="",
        department="",
        tags=tags,
    )


def _render_general(parsed: dict) -> str:
    parts = ["candidate@example.com | 555-123-4567"]
    for entry in parsed.get("experience", []):
        parts.append(f"{entry.get('title', '')} at {entry.get('company', '')}")
        parts.extend(r"\item " + b for b in entry.get("bullets", []))
    skills = parsed.get("skills", [])
    parts.append("Skills: " + ", ".join(skills))
    body = " ".join(parts)
    return (
        r"\documentclass{article}\begin{document}\subsection*{Experience}"
        + body
        + r"\subsection*{Education}B.S. 2024\subsection*{Skills}"
        + ", ".join(skills)
        + r"\end{document}"
    )


def test_nontech_job_terms_are_role_relevant_not_just_title_words():
    """A finance JD must yield its real requirements, not collapse to the title.

    Regression: _job_terms used to return only the title tokens
    (['Senior', 'Financial', 'Analyst']) for non-tech roles because the JD term
    extractor only knows software hints and the body frequency gate was too
    strict. That made the 45%-weighted job-fit axis measure the wrong thing.
    """
    job = _general_job(
        "Senior Financial Analyst",
        "Lead FP&A, build financial models, own month-end close and variance "
        "analysis. Prepare forecasts, manage budgets. CPA and Excel required. "
        "Experience with accounting, reconciliation, and audit preferred.",
        ["occupation:accounting_finance"],
    )
    terms = [t.lower() for t in _job_terms(job)]
    # Real domain requirements are surfaced...
    for required in ("reconciliation", "variance", "forecasts", "budgets"):
        assert required in terms, f"expected {required!r} in {terms}"
    # ...and the seniority word is never a job term.
    assert "senior" not in terms


def test_irrelevant_supporting_evidence_category_is_explicitly_not_applicable():
    job = _general_job(
        "Account Executive",
        "Own enterprise sales relationships and exceed quota.",
        ["occupation:sales"],
    )
    parsed = {
        "experience": [{
            "title": "Account Executive",
            "company": "Acme",
            "bullets": ["Exceeded annual quota by 120%."],
        }],
        "skills": ["Salesforce", "CRM"],
    }

    evaluation = evaluate_resume_quality(
        parsed=parsed,
        content=_render_general(parsed),
        job=job,
    )
    support = next(
        item for item in evaluation["categories"]
        if item["key"] == "supporting_evidence"
    )

    assert evaluation["profile"] == "sales_professional_v1"
    assert support["applicable"] is False
    assert support["max"] == 0
    assert "Not applicable" in support["evidence"][0]


def test_required_healthcare_license_activates_credential_module():
    job = _general_job(
        "Registered Nurse",
        "Requirements\nActive RN license required. Provide patient care.",
        ["occupation:healthcare"],
    )
    parsed = {
        "experience": [{
            "title": "Registered Nurse",
            "company": "Hospital",
            "bullets": ["Provided patient care for 20 patients per shift."],
        }],
        "skills": ["Patient care"],
        "certificates": ["Active RN license"],
    }
    content = _render_general(parsed).replace(
        r"\end{document}",
        r"\subsection*{Licenses & Certifications}Active RN license\end{document}",
    )

    evaluation = evaluate_resume_quality(parsed=parsed, content=content, job=job)
    support = next(
        item for item in evaluation["categories"]
        if item["key"] == "supporting_evidence"
    )

    assert evaluation["profile"] == "healthcare_professional_v1"
    assert support["applicable"] is True
    assert support["max"] == 25
    assert support["score"] > 0


def test_surviving_method_hint_does_not_discard_real_role_terms():
    """A stray method hint must not truncate away the real role vocabulary.

    Regression: `if ordered: return result[:len(ordered)]` meant a marketing JD
    that mentioned "metrics"/"A/B testing" returned only those two terms and
    dropped brand/campaign/content/SEO entirely.
    """
    job = _general_job(
        "Marketing Manager",
        "Own brand campaigns and content strategy. Run A/B testing on paid media, "
        "track metrics, grow demand generation and SEO. Campaign management "
        "and social media required.",
        ["occupation:marketing"],
    )
    terms = [t.lower() for t in _job_terms(job)]
    assert "metrics" in terms  # the surviving hint is still present...
    # ...but so are the real marketing requirements it used to discard.
    assert any(t in terms for t in ("campaign", "campaigns"))
    assert any(t in terms for t in ("content", "strategy", "generation"))


def test_quantified_outcomes_are_detected_per_bullet_for_general_profile():
    """Metric-rich outcome bullets must score the outcomes category.

    Regression: outcomes were detected against the first 40 chars of a
    concatenated title+company+bullets blob line, which never matched the
    rendered artifact, pinning "Demonstrated outcomes" near zero for every
    non-technical resume regardless of quantified impact.
    """
    job = _general_job(
        "Operations Manager",
        "Own operational metrics, improve process efficiency, manage budgets and "
        "vendor relationships. Experience leading cross-functional teams preferred.",
        ["occupation:management_executive"],
    )
    parsed = {
        "contact": {"email": "c@example.com"},
        "experience": [
            {
                "title": "Operations Manager",
                "company": "Corp",
                "bullets": [
                    "Improved process efficiency by 35% across three fulfillment sites.",
                    "Reduced vendor costs by 20% while managing a $5M operating budget.",
                ],
            }
        ],
        "skills": ["Process Improvement", "Budget Management", "Vendor Management"],
    }
    evaluation = evaluate_resume_quality(
        parsed=parsed, content=_render_general(parsed), job=job
    )
    outcomes = next(c for c in evaluation["categories"] if c["key"] == "outcomes")
    assert outcomes["score"] >= 12, evaluation["categories"]


def test_short_tech_hint_does_not_match_inside_unrelated_words():
    """extract_jd_must_surface must use word boundaries, not naive substrings.

    Regression: "Go" matched inside "negotiate", "XP" inside "experience",
    injecting junk skills into non-tech resume plans and scoring.
    """
    from app.services.resume_tailor import extract_jd_must_surface

    surfaced = extract_jd_must_surface(
        "Negotiate contracts and manage regulatory experience for the category."
    )["must_surface"]
    assert "Go" not in surfaced
    assert "XP" not in surfaced
    # Genuine standalone mentions still surface.
    assert "Go" in extract_jd_must_surface("Build backend services in Go and Python.")["must_surface"]


def test_inferred_addition_supported_by_source_is_not_stripped():
    """A tailored resume must never score below the source for a real skill.

    The tailorer sometimes mislabels a skill the candidate actually lists (e.g.
    "JavaScript") as an inferred_claim. Stripping such a phrase when it is
    verbatim in the source evidence dropped the pending tailored score below the
    original resume — defeating the whole point. Genuinely-absent additions
    (e.g. "GraphQL") must still be excluded until confirmed.
    """
    parsed = {
        "contact": {"email": "c@example.com"},
        "experience": [
            {
                "title": "Software Engineering Intern",
                "company": "Acme",
                "bullets": [
                    "Built React and JavaScript interfaces used by 500 customers.",
                ],
            }
        ],
        "skills": ["React", "JavaScript", "TypeScript"],
    }
    content = (
        r"\documentclass{article}\begin{document}\subsection*{Experience}"
        "j@example.com Built React and JavaScript and GraphQL interfaces "
        r"\subsection*{Skills}React, JavaScript, TypeScript\end{document}"
    )
    rewrites = [
        {
            "id": "r1",
            "change_type": "inferred_claim",
            "inferred_additions": ["JavaScript", "GraphQL"],
        }
    ]
    job = SimpleNamespace(
        title="Frontend Engineer",
        description="Build React, JavaScript, TypeScript, and GraphQL web apps.",
        tags=["occupation:software_engineering"],
        experience_level="intern",
        department="engineering",
    )
    evaluation = evaluate_resume_quality(
        parsed=parsed, content=content, job=job, rewrites=rewrites, rewrite_decisions={}
    )
    excluded = evaluation["truthfulness"]["excluded_phrases"]
    # The genuinely-absent inferred claim is still gated...
    assert "GraphQL" in excluded
    # ...but the one the candidate actually lists is not stripped.
    assert "JavaScript" not in excluded


def test_html_scrape_residue_never_becomes_a_job_term():
    """Scraped JDs leave markup residue; it must not be scored against a resume.

    Regression: a nursing JD scored a resume on whether it contained "span" and
    "nbsp" (from stripped <span>/&nbsp;). Markup tokens are not role requirements.
    """
    job = SimpleNamespace(
        title="Registered Nurse",
        description=(
            "<div><span>Provide direct patient care.</span></div>&nbsp;&nbsp; "
            "Administer medications and monitor patient vital signs. nbsp span "
            "Collaborate with physicians on care plans in the ICU."
        ),
        tags=["occupation:healthcare"],
    )
    terms = [t.lower() for t in _job_terms(job)]
    for junk in ("span", "nbsp", "div", "href", "style"):
        assert junk not in terms, f"{junk!r} leaked into {terms}"
    # Real clinical terms still surface.
    assert any(t in terms for t in ("patient", "medications", "care"))
