"""Rendered PDF QA: page count, independent extraction, order, and metrics."""

import shutil

import pytest

from app.services.resume_artifact.latex import (
    render_resume_artifact_pdf,
    verify_rendered_resume_pdf,
)


pytestmark = pytest.mark.skipif(
    not shutil.which("pdflatex") or not shutil.which("pdftotext"),
    reason="PDF QA system tools are unavailable",
)


def _content(*, new_page: bool = False) -> str:
    page_break = r"\newpage" if new_page else ""
    return rf"""
\documentclass[letterpaper]{{article}}
\usepackage[margin=0.5in]{{geometry}}
\usepackage{{hyperref}}
\pagestyle{{empty}}
\begin{{document}}
\textbf{{Candidate Name}}\\
candidate@example.com
\subsection*{{Experience}}
\begin{{itemize}}
\item Improved processing by 25\% for 500 users.
\end{{itemize}}
{page_break}
\subsection*{{Education}}
Bachelor of Science
\subsection*{{Technical Skills}}
Python, SQL
\end{{document}}
"""


def test_rendered_resume_passes_two_parser_text_and_order_checks():
    content = _content()
    pdf = render_resume_artifact_pdf(content)
    result = verify_rendered_resume_pdf(pdf, content)

    assert result["status"] == "passed"
    assert result["page_count"] == 1
    assert result["parser_agreement"] >= 0.85
    assert result["section_order"] == [
        "Experience",
        "Education",
        "Technical Skills",
    ]
    assert result["metric_count"] == 2


def test_rendered_resume_fails_closed_on_second_page():
    with pytest.raises(ValueError, match="must be one page"):
        render_resume_artifact_pdf(_content(new_page=True))
