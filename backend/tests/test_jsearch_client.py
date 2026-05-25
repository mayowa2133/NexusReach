"""Tests for JSearch result normalization."""

from app.clients.jsearch_client import _apply_url


def test_apply_url_prefers_direct_apply_link():
    assert (
        _apply_url(
            {
                "job_apply_link": "https://careers.example.com/jobs/1",
                "job_apply_options": [{"apply_link": "https://aggregator.example.com/jobs/1"}],
                "job_google_link": "https://www.google.com/search?q=job",
            }
        )
        == "https://careers.example.com/jobs/1"
    )


def test_apply_url_falls_back_to_first_option():
    assert (
        _apply_url(
            {
                "job_apply_link": "",
                "job_apply_options": [
                    {"apply_link": ""},
                    {"apply_link": "https://ats.example.com/jobs/2"},
                ],
                "job_google_link": "https://www.google.com/search?q=job",
            }
        )
        == "https://ats.example.com/jobs/2"
    )


def test_apply_url_handles_unexpected_option_shape():
    assert (
        _apply_url(
            {
                "job_apply_link": "",
                "job_apply_options": {"apply_link": "https://ignored.example.com/jobs/3"},
                "job_google_link": "https://www.google.com/search?q=job",
            }
        )
        == "https://www.google.com/search?q=job"
    )
