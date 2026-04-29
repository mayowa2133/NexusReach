from types import SimpleNamespace

from app.services.resume_artifact_service import (
    _build_resume_reuse_candidate,
    _build_redline_resume_artifact_content,
    _default_artifact_plan,
    _derive_project_url,
    _expand_plan_to_fill_page,
    _latex_rich_text,
    _layout_profile,
    _quantifiable_measure_spans,
    _render_resume_latex,
    score_resume_content_against_job,
)


def _make_profile():
    return SimpleNamespace(
        full_name="Mayowa Adesanya",
        target_locations=["Milton, ON"],
        linkedin_url="https://www.linkedin.com/in/mayowa-adesanya/",
        github_url="https://github.com/mayowa2133",
        portfolio_url=None,
        resume_raw=(
            "Mayowa Adesanya\n"
            "359 Kincardine Terrace, Milton, ON |289 681 5743 |adesanym@mcmaster.ca |"
            "https://www.linkedin.com/in/mayowa-adesanya/ |https://github.com/mayowa2133\n"
        ),
        resume_parsed={
            "contact": {
                "address": "359 Kincardine Terrace, Milton, ON",
                "phone": "289 681 5743",
                "email": "adesanym@mcmaster.ca",
                "urls": [
                    "https://www.linkedin.com/in/mayowa-adesanya/",
                    "https://github.com/mayowa2133",
                ],
            },
            "education": [
                {
                    "institution": "McMaster University",
                    "degree": "Honours Computer Science",
                    "field": "Honours Computer Science",
                    "location": "Hamilton, Ontario",
                    "details": ["Cumulative GPA: 3.5/4.0"],
                    "graduation_date": "",
                }
            ],
            "experience": [
                {
                    "company": "CIBC - Personal Banking, Simplii & Direct Investing Technology",
                    "title": "Application/Software Developer",
                    "location": "Toronto, ON",
                    "start_date": "Sep. 2025",
                    "end_date": "Dec. 2025",
                    "description": "",
                    "bullets": [
                        "Built and tested customer-facing mobile product features in the CIBC Mobile App using Swift, Xcode, object-oriented programming, and VIP architecture, improving automated money movement workflows between savings accounts.",
                        "Contributed to the design and implementation of a flagship goal-based savings experience that enabled users to create and manage multiple savings accounts, with the pilot launched to 100+ full-time CIBC staff.",
                        "Participated in Agile ceremonies, code reviews, and cross-functional design discussions, helping translate requirements into scalable, maintainable application behavior while improving reliability through testing, debugging, and Git-based collaboration.",
                        "Built internal tooling and documentation that improved team handoff efficiency across releases.",
                    ],
                },
                {
                    "company": "Amazon Web Services (AWS)",
                    "title": "Cloud Engineer",
                    "location": "Toronto, ON",
                    "start_date": "May 2025",
                    "end_date": "Aug. 2025",
                    "description": "",
                    "bullets": [
                        "Engineered a serverless metadata extraction system using Python, AWS Lambda, Step Functions, and S3, implementing comprehensive error handling across 4 failure scenarios to achieve 100% processing traceability and automated recovery.",
                        "Designed and deployed a secure RESTful API with Amazon API Gateway, enabling external access to the system while enforcing authentication, throttling policies, and ensuring high availability and scalability.",
                        "Built telemetry and monitoring workflows with CloudWatch dashboards, alarms, SNS notifications, and Python health checks, and developed a full-stack AI application with a Streamlit frontend to connect backend services to user-facing workflows.",
                    ],
                }
                ,
                {
                    "company": "Ontario Power Generation (OPG)",
                    "title": "Software Engineer",
                    "location": "Pickering, ON",
                    "start_date": "May 2024",
                    "end_date": "Apr. 2025",
                    "description": "",
                    "bullets": [
                        "Designed and developed a Power BI dashboard backed by SQL to track and visualize required engineering actions by department, improving workflow clarity and team efficiency by 75%.",
                        "Evaluated and validated software used for real-time plant data collection, supporting analysis and visualization workflows used by 5000+ engineers and creating training material for 200+ incoming engineers.",
                        "Performed white-box and black-box testing on Distributed Control Unit logic, improving reliability and accuracy by 15% while strengthening debugging, validation, and performance-focused engineering discipline.",
                    ],
                },
            ],
            "projects": [
                {
                    "name": "ClipForge",
                    "description": "",
                    "link_label": "GitHub: ClipForge",
                    "technologies": ["Next.js", "React", "TypeScript", "Node.js"],
                    "bullets": [
                        "Designed and built an AI-powered short-form video editing platform with a Next.js + React + TypeScript frontend, delivering timeline editing, caption workflows, and multi-format publishing for TikTok, Instagram, and YouTube.",
                        "Built full-stack AI services and LLM orchestration in Node.js + Next.js, integrating OpenAI and Whisper-based multimodal AI pipelines to convert natural-language prompts into validated timeline edits and structured draft recipes with deterministic guardrails.",
                        "Engineered production-grade reliability through export preflight validation, diagnostics, background workers, local-first persistence backed by IndexedDB, and 100+ TypeScript tests, including Playwright/Cypress-style end-to-end testing workflows.",
                    ],
                },
                {
                    "name": "SignalDraft",
                    "description": "",
                    "link_label": "GitHub: SignalDraft",
                    "technologies": ["Python", "FastAPI", "LangGraph", "LangSmith"],
                    "bullets": [
                        "Built a stateful AI agent workflow in Python using LangGraph for inbox classification, field extraction, action routing, reply drafting, and human-in-the-loop review with typed structured outputs.",
                        "Shipped a local-first full-stack AI application with FastAPI, SQLite, Streamlit, and Pydantic, with persisted run history, candidate context, clean API boundaries, and strong observability through LangSmith and LLM evaluation workflows.",
                    ],
                },
                {
                    "name": "NBA Player Performance Prediction System",
                    "description": "",
                    "link_label": "GitHub: nba-win-prediction",
                    "technologies": ["Python", "XGBoost"],
                    "bullets": [
                        "Built a Python machine learning pipeline using XGBoost and ensemble models to predict NBA player props, improving calibration with quantile regression.",
                        "Engineered 70+ features from rolling stats, Vegas lines, injury status, and matchup context, and developed a real-time Odds API ingestion workflow demonstrating scalable data integration and performance-aware decision systems.",
                    ],
                }
            ],
            "skills_by_category": {
                "Languages": ["C", "C++", "Java", "Python", "JavaScript", "TypeScript", "HTML", "CSS", "SQL", "NoSQL", "MySQL", "Swift"],
                "Technologies": ["AWS", "Terraform", "Power BI", "Streamlit", "React", "Node.js", "Git", "OpenAI", "LangGraph", "LangChain", "LangSmith", "Xcode"],
                "Methodologies": ["Agile", "Scrum", "Object-Oriented Programming", "Machine Learning", "NLP", "Data Visualization", "End-to-End Testing"],
            },
            "skills": ["Python", "JavaScript", "TypeScript", "HTML", "CSS", "React", "Node.js", "AWS", "Git", "Playwright", "Cypress", "RESTful APIs", "CI/CD", "telemetry"],
            "certificates": [
                "JavaScript Algorithms and Data Structures, freeCodeCamp (February 2023)",
                "AWS Certified Solutions Architect – Associate (SAA), AWS (July 2025)",
                "AWS Certified AI Practitioner, AWS (July 2025)",
            ],
        },
    )


def test_render_resume_latex_preserves_resume_structure_and_metrics():
    profile = _make_profile()
    user = SimpleNamespace(email="adesanym@mcmaster.ca")
    job = SimpleNamespace(
        title="Software Engineer 1 - Fullstack",
        company_name="Intuit",
        description=(
            "Design, build, and maintain scalable web applications using ReactJS, JavaScript, HTML, and CSS. "
            "Build responsive, accessible experiences and automated test coverage."
        ),
    )
    tailored = SimpleNamespace(
        skills_to_emphasize=["React", "JavaScript", "HTML", "CSS"],
        skills_to_add=["Responsive Design"],
        keywords_to_add=["Playwright", "Accessibility", "Cypress", "CI/CD", "telemetry"],
        bullet_rewrites=[
            {
                "section": "experience",
                "experience_index": 1,
                "original": profile.resume_parsed["experience"][1]["bullets"][0],
                "rewritten": (
                    "Engineered a serverless metadata extraction system using Python, AWS Lambda, Step Functions, and S3, "
                    "implementing comprehensive error handling across 4 failure scenarios to achieve 100% processing traceability "
                    "and automated recovery while integrating frontend-facing services."
                ),
            },
            {
                "section": "projects",
                "project_index": 0,
                "original": profile.resume_parsed["projects"][0]["bullets"][0],
                "rewritten": (
                    "Designed and built an AI-powered short-form video editing platform with a Next.js + React + TypeScript frontend, "
                    "delivering responsive web workflows, caption tooling, and multi-format publishing for TikTok, Instagram, and YouTube."
                ),
            }
        ],
    )
    artifact_plan = {
        "experience": [
            {"index": 0, "selected_bullets": [0, 1, 2], "priority": 1},
            {"index": 1, "selected_bullets": [0, 1, 2], "priority": 2},
            {"index": 2, "selected_bullets": [0, 1, 2], "priority": 3},
        ],
        "projects": [
            {"index": 0, "selected_bullets": [0, 1, 2], "priority": 1},
            {"index": 1, "selected_bullets": [0, 1], "priority": 2},
            {"index": 2, "selected_bullets": [0, 1], "priority": 3},
        ],
        "project_order": [0, 1, 2],
        "skills_focus": ["React", "TypeScript", "Playwright", "Accessibility", "Cypress", "CI/CD"],
        "bold_phrases": ["React", "TypeScript", "responsive", "RESTful API"],
    }

    latex = _render_resume_latex(
        profile=profile,
        user=user,
        job=job,
        tailored=tailored,
        artifact_plan=artifact_plan,
    )

    assert "359 Kincardine Terrace, Milton, ON" in latex
    assert "Cloud Engineer" in latex
    assert "Toronto, ON" in latex
    assert "4 failure scenarios" in latex
    assert "100\\% processing traceability" in latex
    assert "ClipForge" in latex
    assert "SignalDraft" in latex
    assert "NBA Player Performance Prediction System" in latex
    assert "GitHub: ClipForge" in latex
    assert "\\href{https://github.com/mayowa2133/ClipForge}{GitHub: ClipForge}" in latex
    assert "\\href{https://github.com/mayowa2133/SignalDraft}{GitHub: SignalDraft}" in latex
    assert "\\subsection*{Certificates}" in latex
    assert "\\textbf{Relevant}" in latex
    assert "\\textbf{React}" in latex
    assert "\\textbf{HTML}" in latex or "\\textbf{CSS}" in latex
    assert "\\textbf{responsive} web workflows" in latex
    assert "\\textbf{4 failure scenarios}" in latex
    assert "\\textbf{100\\% processing traceability}" in latex
    assert "\\textbf{100+ full-time CIBC staff}" in latex
    assert "Playwright" in latex
    assert "Cypress" in latex


def test_latex_rich_text_bolds_quantifiable_measures_without_overmatching_years():
    text = (
        "Shipped in 2025, improved activation by 35% for 12,000 users, "
        "and added 100+ TypeScript tests with a 3.5/4.0 reliability score."
    )

    rendered = _latex_rich_text(text, ["TypeScript"])

    assert "Shipped in 2025" in rendered
    assert "\\textbf{2025}" not in rendered
    assert "\\textbf{35\\%}" in rendered
    assert "\\textbf{12,000 users}" in rendered
    assert "\\textbf{100+ TypeScript tests}" in rendered
    assert "\\textbf{3.5/4.0 reliability score}" in rendered


def test_quantifiable_measure_spans_skip_version_style_tokens():
    text = "Used HTML5, AWS S3, and OAuth 2.0 for 5000+ engineers."
    spans = [text[start:end] for start, end in _quantifiable_measure_spans(text)]

    assert "HTML5" not in spans
    assert "S3" not in spans
    assert "2.0" in spans
    assert "5000+ engineers" in spans


def test_default_artifact_plan_matches_approved_fullstack_shape():
    profile = _make_profile()
    job = SimpleNamespace(
        title="Software Engineer 1 - Fullstack",
        company_name="Intuit",
        description=(
            "Design, build, and maintain scalable web applications using ReactJS, JavaScript, HTML, CSS, and TypeScript. "
            "Build responsive experiences, RESTful APIs, and automated test coverage using Playwright or Cypress while collaborating cross-functionally."
        ),
    )
    tailored = SimpleNamespace(
        skills_to_emphasize=["React", "JavaScript", "TypeScript", "HTML", "CSS"],
        skills_to_add=["responsive UI development", "component-based architecture"],
        keywords_to_add=["RESTful APIs", "Playwright", "Cypress", "CI/CD", "telemetry", "Git"],
    )

    plan = _default_artifact_plan(profile.resume_parsed, job, tailored)

    assert [item["selected_bullets"] for item in plan["experience"]] == [[0, 1, 2], [0, 1, 2], [0, 1, 2]]
    assert [item["selected_bullets"] for item in plan["projects"]] == [[0, 1, 2], [0, 1], [0, 1]]
    assert plan["project_order"] == [0, 1, 2]
    assert plan["skills_focus"][:6] == ["React", "JavaScript", "TypeScript", "HTML", "CSS", "Next.js"]
    assert "Playwright" in plan["skills_focus"]
    assert "Cypress" in plan["skills_focus"]


def test_expand_plan_to_fill_page_adds_more_bullets_when_sparse():
    profile = _make_profile()
    job = SimpleNamespace(
        title="Software Engineer 1 - Fullstack",
        company_name="Intuit",
        description="React JavaScript TypeScript HTML CSS Playwright accessibility testing frontend RESTful APIs",
    )
    sparse_plan = {
        "experience": [{"index": 0, "selected_bullets": [0], "priority": 1}],
        "projects": [{"index": 0, "selected_bullets": [0], "priority": 1}],
        "project_order": [0],
        "skills_focus": ["React", "TypeScript"],
        "bold_phrases": ["React", "TypeScript"],
    }

    expanded = _expand_plan_to_fill_page(profile.resume_parsed, job, sparse_plan)

    total_bullets = sum(len(item.get("selected_bullets", [])) for item in expanded["experience"])
    total_bullets += sum(len(item.get("selected_bullets", [])) for item in expanded["projects"])
    assert total_bullets >= 16


def test_derive_project_url_falls_back_to_contact_urls_when_profile_missing():
    """A user who only uploaded a resume (and never edited their profile) still
    gets clickable project links because the GitHub URL is recovered from the
    parsed contact section."""
    profile = SimpleNamespace(github_url=None, linkedin_url=None, portfolio_url=None)
    contact = {"urls": ["https://www.linkedin.com/in/mayowa-adesanya/", "https://github.com/mayowa2133"]}
    project = {"name": "ClipForge", "link_label": "GitHub: ClipForge", "url": None}

    url = _derive_project_url(project, profile, contact)

    assert url == "https://github.com/mayowa2133/ClipForge"


def test_derive_project_url_prefers_explicit_url():
    profile = SimpleNamespace(github_url="https://github.com/wronguser")
    project = {
        "name": "ClipForge",
        "link_label": "GitHub: ClipForge",
        "url": "https://gitlab.com/team/clipforge",
    }
    assert _derive_project_url(project, profile, {}) == "https://gitlab.com/team/clipforge"


def test_derive_project_url_returns_none_without_any_github_signal():
    profile = SimpleNamespace(github_url=None)
    project = {"name": "ClipForge", "link_label": None, "url": None}
    assert _derive_project_url(project, profile, {"urls": []}) is None


def test_render_resume_latex_recovers_project_links_from_contact_when_profile_url_missing():
    """End-to-end render: profile.github_url is empty (typical for a fresh resume
    upload), but the parsed resume contact has the GitHub URL. The artifact must
    still emit \\href{...} links for every project."""
    profile = _make_profile()
    profile.github_url = None
    user = SimpleNamespace(email="adesanym@mcmaster.ca")
    job = SimpleNamespace(
        title="Software Engineer 1 - Fullstack",
        company_name="Intuit",
        description="React, JavaScript, TypeScript, HTML, CSS, responsive web applications, RESTful APIs.",
    )
    tailored = SimpleNamespace(
        skills_to_emphasize=["React", "JavaScript", "TypeScript"],
        skills_to_add=["responsive UI development"],
        keywords_to_add=["Playwright", "CI/CD"],
        bullet_rewrites=[],
    )

    latex = _render_resume_latex(profile=profile, user=user, job=job, tailored=tailored)

    assert "\\href{https://github.com/mayowa2133/ClipForge}{GitHub: ClipForge}" in latex
    assert "\\href{https://github.com/mayowa2133/SignalDraft}{GitHub: SignalDraft}" in latex
    assert "\\href{https://github.com/mayowa2133/nba-win-prediction}" in latex


def test_render_resume_latex_default_plan_keeps_full_fullstack_shape():
    """When generate is called without an explicit artifact_plan and no LLM
    runs (job description triggers the default planner only), the rendered LaTeX
    must still contain all 9 experience bullets and 7 project bullets."""
    profile = _make_profile()
    user = SimpleNamespace(email="adesanym@mcmaster.ca")
    job = SimpleNamespace(
        title="Software Engineer 1 - Fullstack",
        company_name="Intuit",
        description=(
            "Build responsive web applications with ReactJS, JavaScript, HTML, CSS, and TypeScript. "
            "Write Playwright/Cypress tests, ship RESTful APIs, and collaborate cross-functionally."
        ),
    )
    tailored = SimpleNamespace(
        skills_to_emphasize=["React", "JavaScript", "TypeScript"],
        skills_to_add=["responsive UI development"],
        keywords_to_add=["Playwright", "Cypress", "CI/CD"],
        bullet_rewrites=[],
    )

    latex = _render_resume_latex(profile=profile, user=user, job=job, tailored=tailored)

    item_count = latex.count("\\item ")
    assert item_count >= 16, f"expected >=16 \\item entries, got {item_count}"
    for project_name in ("ClipForge", "SignalDraft", "NBA Player Performance Prediction System"):
        assert project_name in latex


def test_render_resume_latex_sparse_plan_does_not_drop_remaining_bullets():
    """Even when the artifact_plan only marks a single bullet for one experience,
    the renderer must still produce the other top experiences with their bullets
    so we do not silently drop content."""
    profile = _make_profile()
    user = SimpleNamespace(email="adesanym@mcmaster.ca")
    job = SimpleNamespace(
        title="Software Engineer 1 - Fullstack",
        company_name="Intuit",
        description="React JavaScript TypeScript HTML CSS responsive frontend RESTful APIs",
    )
    tailored = SimpleNamespace(
        skills_to_emphasize=["React"], skills_to_add=[], keywords_to_add=[], bullet_rewrites=[],
    )
    sparse_plan = {
        "experience": [{"index": 0, "selected_bullets": [0], "priority": 1}],
        "projects": [{"index": 0, "selected_bullets": [0], "priority": 1}],
        "project_order": [0, 1, 2],
        "skills_focus": ["React"],
        "bold_phrases": ["React"],
    }

    latex = _render_resume_latex(
        profile=profile, user=user, job=job, tailored=tailored, artifact_plan=sparse_plan,
    )

    assert "Cloud Engineer" in latex
    assert "Ontario Power Generation" in latex
    assert "SignalDraft" in latex


def test_layout_profile_grows_font_for_sparse_density():
    """Sparse artifacts must render at a larger font/line-spread so the page
    fills naturally instead of leaving trailing whitespace."""
    sparse_font, _, sparse_spread = _layout_profile(
        experience=[{"selected_bullets": ["x"]}],
        projects=[{"selected_bullets": ["y"]}],
        certificates=[],
    )
    full_font, _, full_spread = _layout_profile(
        experience=[{"selected_bullets": ["x"] * 3}] * 3,
        projects=[{"selected_bullets": ["y"] * 3}, {"selected_bullets": ["y"] * 2}, {"selected_bullets": ["y"] * 2}],
        certificates=["c1", "c2", "c3"],
    )

    assert float(sparse_font.replace("pt", "")) >= float(full_font.replace("pt", "")) + 1.0
    assert float(sparse_spread) >= float(full_spread)


def test_frontend_fullstack_experience_prefers_first_two_plus_best_relevant_third():
    profile = _make_profile()
    job = SimpleNamespace(
        title="Software Engineer 1 - Fullstack",
        company_name="Intuit",
        description=(
            "Build responsive component-based web applications, write automated tests, debug issues, "
            "participate in CI/CD, and collaborate cross-functionally."
        ),
    )
    tailored = SimpleNamespace(
        skills_to_emphasize=["React", "JavaScript", "TypeScript"],
        skills_to_add=["responsive UI development"],
        keywords_to_add=["testing", "debugging", "CI/CD", "cross-functional collaboration"],
    )

    profile.resume_parsed["experience"][2]["bullets"] = [
        "Designed and developed a Power BI dashboard backed by SQL to track and visualize required engineering actions by department, improving workflow clarity and team efficiency by 75%.",
        "Evaluated and validated software used for real-time plant data collection, supporting analysis and visualization workflows used by 5000+ engineers and creating training material for 200+ incoming engineers.",
        "Installed and configured SIM-PC on a virtual machine to simulate control logic operations, improving simulation capabilities by 200%.",
        "Performed white-box and black-box testing on Distributed Control Unit logic, improving reliability and accuracy by 15% while strengthening debugging, validation, and performance-focused engineering discipline.",
    ]

    plan = _default_artifact_plan(profile.resume_parsed, job, tailored)

    assert plan["experience"][2]["selected_bullets"] == [0, 1, 3]


# ---------------------------------------------------------------------------
# Decision gating tests
# ---------------------------------------------------------------------------

from app.services.resume_artifact_service import _filter_rewrites_by_decisions  # noqa: E402
from app.services.resume_tailor import _normalize_bullet_rewrites  # noqa: E402


def _rewrites():
    return [
        {"id": "rw-keyword", "change_type": "keyword", "original": "A", "rewritten": "A2"},
        {"id": "rw-reframe", "change_type": "reframe", "original": "B", "rewritten": "B2"},
        {"id": "rw-inferred", "change_type": "inferred_claim", "original": "C", "rewritten": "C2"},
    ]


def test_filter_pending_drops_inferred_keeps_others():
    allowed = _filter_rewrites_by_decisions(_rewrites(), {})
    ids = {r["id"] for r in allowed}
    assert ids == {"rw-keyword", "rw-reframe"}


def test_filter_accepted_includes_inferred():
    allowed = _filter_rewrites_by_decisions(
        _rewrites(), {"rw-inferred": "accepted"}
    )
    assert any(r["id"] == "rw-inferred" for r in allowed)


def test_filter_rejected_excludes_all_change_types():
    allowed = _filter_rewrites_by_decisions(
        _rewrites(),
        {"rw-keyword": "rejected", "rw-reframe": "rejected", "rw-inferred": "rejected"},
    )
    assert allowed == []


def test_filter_auto_accept_flag_includes_pending_inferred():
    allowed = _filter_rewrites_by_decisions(
        _rewrites(), {}, auto_accept_inferred=True,
    )
    ids = {r["id"] for r in allowed}
    assert ids == {"rw-keyword", "rw-reframe", "rw-inferred"}


def test_filter_rejected_overrides_auto_accept():
    allowed = _filter_rewrites_by_decisions(
        _rewrites(), {"rw-inferred": "rejected"}, auto_accept_inferred=True,
    )
    assert not any(r["id"] == "rw-inferred" for r in allowed)


def test_normalize_bullet_rewrites_fills_missing_fields():
    rewrites = _normalize_bullet_rewrites([
        {"original": "Built API.", "rewritten": "Built RESTful API with telemetry."},
        {
            "original": "Did X.",
            "rewritten": "Did X with accessible, component-based, responsive UI.",
            "change_type": "inferred_claim",
            "inferred_additions": ["accessible", "component-based"],
        },
    ])
    assert len(rewrites) == 2
    assert all("id" in r for r in rewrites)
    # Second rewrite preserves declared change_type + flag
    assert rewrites[1]["change_type"] == "inferred_claim"
    assert rewrites[1]["requires_user_confirm"] is True
    assert rewrites[1]["inferred_additions"] == ["accessible", "component-based"]


def test_normalize_bullet_rewrites_classifies_inferred_from_delta():
    rewrites = _normalize_bullet_rewrites([
        {
            "original": "Shipped features.",
            "rewritten": (
                "Shipped responsive, accessible, component-based web UI features "
                "with Playwright coverage and telemetry."
            ),
        },
    ])
    assert rewrites[0]["change_type"] == "inferred_claim"
    assert rewrites[0]["requires_user_confirm"] is True


def test_build_redline_resume_artifact_content_marks_rendered_edits():
    content = "\n".join([
        r"\documentclass{article}",
        r"\begin{document}",
        r"\begin{itemize}",
        r"\item Built RESTful APIs with React dashboards, improving release confidence by 35%.",
        r"\end{itemize}",
        r"\end{document}",
    ])
    redline = _build_redline_resume_artifact_content(
        content,
        [
            {
                "id": "rw-1",
                "change_type": "reframe",
                "original": "Built APIs for internal tools.",
                "rewritten": (
                    "Built RESTful APIs with React dashboards, "
                    "improving release confidence by 35%."
                ),
            }
        ],
        {"rw-1": "accepted"},
    )

    assert r"\usepackage[normalem]{ulem}" in redline
    assert r"\usepackage{soul}" in redline
    assert r"\soulregister\textbf7" in redline
    assert r"\sout{for internal tools.}" in redline
    assert r"\hl{RESTful " in redline
    assert "with React dashboards" in redline
    assert r"\textbf{35\%}" in redline


def test_build_redline_resume_artifact_content_handles_short_bullets():
    content = "\n".join([
        r"\documentclass{article}",
        r"\usepackage[dvipsnames]{xcolor}",
        r"\begin{document}",
        r"\begin{itemize}",
        r"\item Led QA automation.",
        r"\end{itemize}",
        r"\end{document}",
    ])
    redline = _build_redline_resume_artifact_content(
        content,
        [
            {
                "id": "rw-1",
                "change_type": "reframe",
                "original": "Led QA.",
                "rewritten": "Led QA automation.",
            }
        ],
        {"rw-1": "accepted"},
    )

    assert redline.count(r"\usepackage[dvipsnames]{xcolor}") == 1
    assert r"\usepackage{xcolor}" not in redline
    assert r"Led QA {\sethlcolor{green!25}\hl{automation.}}" in redline


def test_resume_reuse_score_ignores_skills_only_matches():
    job = SimpleNamespace(description="Experience with React and TypeScript.")
    content = "\n".join([
        r"\documentclass{article}",
        r"\begin{document}",
        r"\section*{Experience}",
        r"\begin{itemize}",
        r"\item Built customer dashboards and release workflows.",
        r"\end{itemize}",
        r"\subsection*{Technical Skills}",
        "React, TypeScript",
        r"\end{document}",
    ])

    assert score_resume_content_against_job(content, job) == 0.0


def test_build_resume_reuse_candidate_requires_high_body_match():
    artifact = SimpleNamespace(
        content="\n".join([
            r"\documentclass{article}",
            r"\begin{document}",
            r"\section*{Experience}",
            r"\begin{itemize}",
            (
                r"\item Built full-stack React and TypeScript workflows with "
                r"Node.js, REST services, and Agile delivery."
            ),
            r"\end{itemize}",
            r"\subsection*{Technical Skills}",
            "React, TypeScript, Node.js, REST",
            r"\end{document}",
        ])
    )
    source_job = SimpleNamespace(
        title="Full-Stack Software Engineer",
        description="Build full-stack product experiences.",
    )
    target_job = SimpleNamespace(
        title="Full-Stack Software Engineer",
        description=(
            "Build full-stack apps with React, TypeScript, Node.js, REST, "
            "and Agile delivery."
        ),
    )

    candidate = _build_resume_reuse_candidate(
        artifact=artifact,
        source_job=source_job,
        target_job=target_job,
        threshold=80.0,
    )

    assert candidate is not None
    assert candidate["score"] >= 80.0
    assert candidate["job_family"] == "frontend_fullstack"
