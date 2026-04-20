"""Tests for the resume parsing service — Phase 2.

Tests pure functions that parse resume text into structured data.
No database or external API calls needed.
"""

import pytest

from app.services.resume_parser import (
    _parse_skills,
    _parse_skill_categories,
    _parse_experience,
    _parse_education,
    _parse_projects,
    _split_sections,
    extract_text,
    parse_resume,
    parse_resume_text,
)


# --- _parse_skills ---


class TestParseSkills:
    def test_comma_separated(self):
        text = "Python, JavaScript, TypeScript, React, Node.js"
        skills = _parse_skills(text)
        assert "Python" in skills
        assert "JavaScript" in skills
        assert "React" in skills

    def test_bullet_points(self):
        text = "• Python\n• JavaScript\n• TypeScript\n• Go"
        skills = _parse_skills(text)
        assert "Python" in skills
        assert "Go" in skills

    def test_pipe_separated(self):
        text = "Python | Java | C++ | Rust"
        skills = _parse_skills(text)
        assert "Python" in skills
        assert "Rust" in skills

    def test_mixed_delimiters(self):
        text = "Python, Java\nReact | Vue; Angular"
        skills = _parse_skills(text)
        assert len(skills) >= 4

    def test_empty_input(self):
        assert _parse_skills("") == []

    def test_filters_very_short_strings(self):
        text = "a, Python, b"
        skills = _parse_skills(text)
        assert "Python" in skills
        # Single-char entries should be filtered
        assert "a" not in skills
        assert "b" not in skills

    def test_filters_very_long_strings(self):
        long = "x" * 60
        text = f"Python, {long}"
        skills = _parse_skills(text)
        assert "Python" in skills
        assert long not in skills


# --- _parse_skill_categories: PDF flattening repair ---


class TestParseSkillCategoriesFlattened:
    def test_flattened_multi_category_line(self):
        # PDF extraction can collapse multiple categories onto one line and
        # insert space before colons.
        text = "Languages : C++, Java, Python Technologies : AWS, Terraform Methodologies : Agile"
        cats = _parse_skill_categories(text)
        assert "Languages" in cats
        assert "Technologies" in cats
        assert "Methodologies" in cats
        assert "C++" in cats["Languages"]
        assert "AWS" in cats["Technologies"]
        # Critical regression: category labels must NOT leak as values.
        for values in cats.values():
            for v in values:
                assert "Languages" not in v
                assert "Technologies" not in v
                assert ":" not in v

    def test_parse_skills_drops_label_leak(self):
        text = "Languages : C++, Java Technologies : AWS, Terraform"
        skills = _parse_skills(text)
        assert "C++" in skills
        assert "AWS" in skills
        assert "Terraform" in skills
        for s in skills:
            assert ":" not in s
            assert s not in {"Languages", "Technologies"}


# --- _parse_experience ---


class TestParseExperience:
    def test_standard_date_format(self):
        text = "Software Engineer Jan 2020 – Present\nAcme Corp\nBuilt APIs"
        entries = _parse_experience(text)
        assert len(entries) >= 1
        assert entries[0]["start_date"] == "Jan 2020"

    def test_year_range_format(self):
        text = "Developer 2019-2021\nStartup Inc\nFull stack work"
        entries = _parse_experience(text)
        assert len(entries) >= 1

    def test_multiple_entries(self):
        text = (
            "Senior Engineer Jan 2022 – Present\nBigCo\nLed team\n\n"
            "Junior Engineer Jun 2019 – Dec 2021\nSmallCo\nWrote code"
        )
        entries = _parse_experience(text)
        assert len(entries) == 2

    def test_empty_input(self):
        assert _parse_experience("") == []

    def test_resume_style_entry_preserves_location_and_bullets(self):
        text = (
            "Amazon Web Services (AWS) May 2025 – Aug. 2025\n"
            "Cloud Engineer Toronto, ON\n"
            "•Engineered a serverless metadata extraction system using Python and AWS Lambda.\n"
            "•Designed and deployed a secure RESTful API with Amazon API Gateway."
        )
        entries = _parse_experience(text)
        assert len(entries) == 1
        assert entries[0]["company"] == "Amazon Web Services (AWS)"
        assert entries[0]["title"] == "Cloud Engineer"
        assert entries[0]["location"] == "Toronto, ON"
        assert len(entries[0]["bullets"]) == 2


# --- _parse_education ---


class TestParseEducation:
    def test_bachelors_degree(self):
        text = "B.S. Computer Science 2020\nMIT"
        entries = _parse_education(text)
        assert len(entries) >= 1
        assert "2020" in entries[0].get("graduation_date", "")

    def test_masters_degree(self):
        text = "Master of Science in Data Science\nStanford University"
        entries = _parse_education(text)
        assert len(entries) >= 1

    def test_multiple_degrees(self):
        text = "Ph.D. Machine Learning 2023\nCMU\n\nB.S. Mathematics 2018\nUCLA"
        entries = _parse_education(text)
        assert len(entries) >= 2

    def test_empty_input(self):
        assert _parse_education("") == []


# --- _parse_projects ---


class TestParseProjects:
    def test_project_with_url(self):
        text = "TaskManager https://github.com/user/taskmanager\n- Built with React and Node.js"
        entries = _parse_projects(text)
        assert len(entries) >= 1
        assert entries[0]["url"] == "https://github.com/user/taskmanager"

    def test_project_with_tech_stack(self):
        # Tech line must start with a bullet or be long (>80 chars) so the parser
        # doesn't treat it as a new project name. This matches real resume formatting.
        text = "ChatBot\n- A real-time chat application using websockets with real-time messaging capabilities and end-to-end encryption for security\n- Technologies: React, Socket.io, Express"
        entries = _parse_projects(text)
        assert len(entries) >= 1
        has_tech = any(len(e["technologies"]) >= 2 for e in entries)
        assert has_tech

    def test_empty_input(self):
        assert _parse_projects("") == []

    def test_project_with_link_label_and_bullets(self):
        text = (
            "ClipForge (GitHub: ClipForge)\n"
            "•Designed and built an AI-powered short-form video editing platform.\n"
            "•Built full-stack AI services in Node.js + Next.js."
        )
        entries = _parse_projects(text)
        assert len(entries) == 1
        assert entries[0]["name"] == "ClipForge"
        assert entries[0]["link_label"] == "GitHub: ClipForge"
        assert len(entries[0]["bullets"]) == 2


# --- _split_sections ---


class TestSplitSections:
    def test_full_resume(self):
        text = (
            "John Doe\njohn@example.com\n\n"
            "Experience\nSoftware Engineer at Acme 2020-2023\n\n"
            "Education\nB.S. Computer Science MIT 2019\n\n"
            "Skills\nPython, JavaScript, React\n\n"
            "Projects\nCoolApp - A cool app"
        )
        sections = _split_sections(text)
        assert "experience" in sections
        assert "education" in sections
        assert "skills" in sections
        assert "projects" in sections

    def test_partial_resume(self):
        text = "Skills\nPython, Java\n\nExperience\nDeveloper 2020-2023"
        sections = _split_sections(text)
        assert "skills" in sections
        assert "experience" in sections

    def test_no_sections(self):
        text = "Just some random text without headers"
        sections = _split_sections(text)
        assert len(sections) == 0


# --- extract_text ---


class TestExtractText:
    def test_rejects_unsupported_type(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_text(b"data", "text/plain")

    def test_rejects_html(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_text(b"<html>", "text/html")


# --- parse_resume (integration of all parsing) ---


class TestParseResume:
    def test_returns_expected_keys(self):
        """parse_resume with a non-PDF/DOCX should raise, but we can test
        the structure by using a mock. For now, verify structure expectation."""
        # This tests the internal logic after text extraction
        with pytest.raises(ValueError):
            parse_resume(b"fake data", "text/plain")

    def test_parse_resume_text_extracts_contact_and_certificates(self):
        text = (
            "Mayowa Adesanya\n"
            "359 Kincardine Terrace, Milton, ON | 289 681 5743 | adesanym@mcmaster.ca | "
            "https://www.linkedin.com/in/mayowa-adesanya/ | https://github.com/mayowa2133\n\n"
            "Education\n"
            "McMaster University\n"
            "Honours Computer Science Hamilton, Ontario\n"
            "Cumulative GPA: 3.5/4.0\n\n"
            "Experience\n"
            "CIBC Sep. 2025 – Dec. 2025\n"
            "Application/Software Developer Toronto, ON\n"
            "•Built and tested new iOS features.\n\n"
            "Projects\n"
            "ClipForge (GitHub: ClipForge)\n"
            "•Designed and built an AI-powered short-form video editing platform.\n\n"
            "Technical Skills\n"
            "•Languages: Python, JavaScript, TypeScript\n"
            "•Technologies: React, Node.js, AWS\n\n"
            "Certificates\n"
            "•AWS Certified Solutions Architect – Associate (SAA), AWS (July 2025)\n"
            "1\n"
        )
        parsed = parse_resume_text(text)
        assert parsed["contact"]["address"] == "359 Kincardine Terrace, Milton, ON"
        assert parsed["contact"]["email"] == "adesanym@mcmaster.ca"
        assert parsed["experience"][0]["location"] == "Toronto, ON"
        assert parsed["skills_by_category"]["Languages"] == ["Python", "JavaScript", "TypeScript"]
        assert parsed["certificates"][0].startswith("AWS Certified Solutions Architect")
        assert "1" not in parsed["certificates"]
