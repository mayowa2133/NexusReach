"""Rendered seniority × occupation benchmark with raster-level QA snapshots."""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.occupation_taxonomy import OCCUPATIONS
from app.services.resume_artifact.latex import (
    _render_resume_latex,
    render_resume_artifact_pdf,
    verify_rendered_resume_pdf,
)
from app.services.resume_artifact.plan import artifact_section_policy


pytestmark = pytest.mark.skipif(
    not shutil.which("pdflatex")
    or not shutil.which("pdftotext")
    or not shutil.which("pdftoppm"),
    reason="TeX and Poppler are required for the rendered benchmark",
)


def _profile():
    return SimpleNamespace(
        full_name="Candidate Name",
        target_locations=["Toronto, Canada"],
        linkedin_url="https://linkedin.com/in/candidate",
        github_url=None,
        portfolio_url="https://candidate.example",
        resume_raw="Candidate resume",
        resume_parsed={
            "contact": {
                "name": "Candidate Name",
                "email": "candidate@example.com",
                "phone": "416-555-0100",
                "address": "Toronto, Canada",
            },
            "experience": [{
                "title": "Professional Specialist",
                "company": "Example Employer",
                "start_date": "2023",
                "end_date": "Present",
                "bullets": [
                    "Improved service quality by 25% for 500 clients.",
                    "Led cross-functional delivery while preserving compliance and accuracy.",
                ],
            }],
            "education": [{
                "institution": "Example University",
                "degree": "Bachelor of Science",
                "field": "Professional Studies",
                "graduation_date": "2023",
            }],
            "projects": [{
                "name": "Evidence Portfolio",
                "description": "Documented a measurable professional improvement.",
                "technologies": ["Excel"],
                "bullets": ["Documented a 25% improvement using supported evidence."],
            }],
            "skills": ["Excel", "Communication", "Project Management"],
            "skills_by_category": {
                "Languages": [],
                "Technologies": ["Excel"],
                "Methodologies": ["Project Management"],
            },
            "certificates": ["Professional Certification (2025)"],
        },
    )


def _raster_snapshot(pdf: bytes, tmp_path, key: str) -> dict[str, float | int]:
    pdf_path = tmp_path / f"{key}.pdf"
    output_root = tmp_path / key
    pdf_path.write_bytes(pdf)
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-r", "36", "-png", str(pdf_path), str(output_root)],
        check=True,
        capture_output=True,
        timeout=20,
    )
    with Image.open(output_root.with_suffix(".png")) as image:
        grayscale = image.convert("L")
        histogram = grayscale.histogram()
        nonwhite = sum(histogram[:250])
        total = image.width * image.height
        return {
            "width": image.width,
            "height": image.height,
            "ink_ratio": round(nonwhite / total, 4),
        }


@pytest.mark.parametrize("seniority", ["entry", "mid", "senior"])
@pytest.mark.parametrize("occupation", OCCUPATIONS, ids=lambda occupation: occupation.key)
def test_every_occupation_and_seniority_renders_one_page_with_stable_visual_bounds(
    occupation,
    seniority,
    tmp_path,
):
    prefix = {"entry": "Entry Level", "mid": "", "senior": "Senior"}[seniority]
    title = " ".join(filter(None, (prefix, occupation.default_search_queries[0])))
    job = SimpleNamespace(
        title=title,
        company_name="Example Employer",
        description="Deliver measurable outcomes using the stated professional requirements.",
        tags=[f"occupation:{occupation.key}"],
    )
    tailored = SimpleNamespace(
        skills_to_emphasize=[],
        skills_to_add=[],
        keywords_to_add=[],
        bullet_rewrites=[],
    )
    latex = _render_resume_latex(
        profile=_profile(),
        user=SimpleNamespace(email="candidate@example.com"),
        job=job,
        tailored=tailored,
    )
    pdf = render_resume_artifact_pdf(latex)
    qa = verify_rendered_resume_pdf(pdf, latex)
    visual = _raster_snapshot(pdf, tmp_path, f"{occupation.key}-{seniority}")
    policy = artifact_section_policy(job)

    assert qa["status"] == "passed"
    assert qa["page_count"] == 1
    assert qa["parser_agreement"] >= 0.85
    assert visual["width"] == 306
    assert visual["height"] == 396
    assert 0.01 <= visual["ink_ratio"] <= 0.30
    assert policy.labels["experience"] in qa["section_order"]
    assert policy.labels["skills"] in qa["section_order"]
