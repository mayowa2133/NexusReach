from pathlib import Path

from app.clients.newgrad_jobs_client import parse_job_detail_html


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "newgrad_jobs"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


def test_parse_job_detail_html_software_fixture():
    detail = parse_job_detail_html(_fixture("software_detail.html"))

    assert detail["location"] == "Minneapolis, MN"
    assert detail["employment_type"] == "full-time"
    assert detail["remote"] is False
    assert detail["salary_min"] == 93000.0
    assert detail["salary_max"] == 109000.0
    assert detail["level_label"] == "Entry Level"
    assert "Responsibilities" in detail["description"]
    assert "IAM automation team" in detail["description"]


def test_parse_job_detail_html_remote_fixture():
    detail = parse_job_detail_html(_fixture("remote_detail.html"))

    assert detail["location"] == "United States"
    assert detail["employment_type"] == "full-time"
    assert detail["remote"] is True
    assert detail["salary_min"] == 78000.0
    assert detail["salary_max"] == 176000.0
    assert detail["level_label"] == "Entry, Mid Level"


def test_parse_job_detail_html_ux_fixture_without_salary():
    detail = parse_job_detail_html(_fixture("ux_detail_no_salary.html"))

    assert detail["location"] == "Ridgefield, CT"
    assert detail["employment_type"] == "full-time"
    assert detail["remote"] is False
    assert detail["salary_min"] is None
    assert detail["salary_max"] is None
    assert detail["level_label"] == "New Grad"
    assert "UX research co-op" in detail["description"]


def test_parse_job_detail_html_ignores_hidden_closed_markup():
    detail = parse_job_detail_html(_fixture("hidden_closed_detail.html"))

    assert detail["closed"] is False
    assert "This job has closed." not in detail["description"]
    assert "Hidden closed text" in detail["description"]
