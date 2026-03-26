"""Tests for LinkedIn URL normalization and dedup utilities."""

import pytest

from app.utils.linkedin import normalize_linkedin_url


class TestNormalizeLinkedinUrl:
    """Tests for normalize_linkedin_url."""

    def test_standard_url(self):
        assert (
            normalize_linkedin_url("https://www.linkedin.com/in/johndoe")
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_trailing_slash(self):
        assert (
            normalize_linkedin_url("https://www.linkedin.com/in/johndoe/")
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_query_params_stripped(self):
        assert (
            normalize_linkedin_url(
                "https://www.linkedin.com/in/johndoe?trk=profile"
            )
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_fragment_stripped(self):
        assert (
            normalize_linkedin_url(
                "https://www.linkedin.com/in/johndoe#section"
            )
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_case_normalization(self):
        assert (
            normalize_linkedin_url("https://www.linkedin.com/in/JohnDoe")
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_http_to_https(self):
        assert (
            normalize_linkedin_url("http://www.linkedin.com/in/johndoe")
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_without_www(self):
        assert (
            normalize_linkedin_url("https://linkedin.com/in/johndoe")
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_no_scheme(self):
        assert (
            normalize_linkedin_url("linkedin.com/in/johndoe")
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_www_no_scheme(self):
        assert (
            normalize_linkedin_url("www.linkedin.com/in/johndoe")
            == "https://www.linkedin.com/in/johndoe"
        )

    def test_none_returns_none(self):
        assert normalize_linkedin_url(None) is None

    def test_empty_returns_none(self):
        assert normalize_linkedin_url("") is None

    def test_whitespace_returns_none(self):
        assert normalize_linkedin_url("   ") is None

    def test_non_linkedin_url_returns_none(self):
        assert normalize_linkedin_url("https://github.com/johndoe") is None

    def test_linkedin_company_page_returns_none(self):
        assert (
            normalize_linkedin_url("https://www.linkedin.com/company/acme")
            is None
        )

    def test_linkedin_jobs_page_returns_none(self):
        assert (
            normalize_linkedin_url("https://www.linkedin.com/jobs/view/123")
            is None
        )

    def test_with_extra_path_segments(self):
        """Extra segments after the slug are ignored; slug is extracted."""
        assert (
            normalize_linkedin_url(
                "https://www.linkedin.com/in/johndoe/detail/contact-info/"
            )
            == "https://www.linkedin.com/in/johndoe"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/in/johndoe",
            "https://linkedin.com/in/JohnDoe/",
            "http://www.linkedin.com/in/johndoe?foo=bar",
            "linkedin.com/in/JOHNDOE#section",
        ],
    )
    def test_all_variants_normalize_same(self, url: str):
        assert (
            normalize_linkedin_url(url)
            == "https://www.linkedin.com/in/johndoe"
        )
