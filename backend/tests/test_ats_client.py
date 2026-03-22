"""Unit tests for ATS public board clients."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.clients.ats_client import (
    ExactJobFetchError,
    fetch_exact_job,
    parse_ats_job_url,
    search_ashby,
    search_greenhouse,
    search_lever,
    search_workable,
)

def _mock_httpx_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def _mock_client_with(response):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=response)
    return mock_client


class TestSearchGreenhouse:
    async def test_returns_full_board_by_default(self):
        jobs = [
            {
                "id": index,
                "title": f"Role {index}",
                "absolute_url": f"https://example.com/{index}",
                "location": {"name": "Remote"},
                "content": f"Description {index}",
                "updated_at": "2026-03-18",
            }
            for index in range(25)
        ]
        mock_client = _mock_client_with(
            _mock_httpx_response({"name": "Affirm", "jobs": jobs})
        )

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_greenhouse("affirm")

        assert len(results) == 25
        assert results[-1]["title"] == "Role 24"

    async def test_applies_explicit_limit_after_normalization(self):
        jobs = [
            {
                "id": index,
                "title": f"Role {index}",
                "absolute_url": f"https://example.com/{index}",
                "location": {"name": "Remote"},
                "content": f"Description {index}",
                "updated_at": "2026-03-18",
            }
            for index in range(10)
        ]
        mock_client = _mock_client_with(
            _mock_httpx_response({"name": "Affirm", "jobs": jobs})
        )

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_greenhouse("affirm", limit=3)

        assert len(results) == 3
        assert results[2]["title"] == "Role 2"


class TestSearchLever:
    async def test_returns_full_board_by_default(self):
        postings = [
            {
                "id": f"lever-{index}",
                "text": f"Role {index}",
                "hostedUrl": f"https://example.com/{index}",
                "descriptionPlain": f"Description {index}",
                "categories": {"location": "Remote", "department": "Engineering"},
            }
            for index in range(25)
        ]
        mock_client = _mock_client_with(_mock_httpx_response(postings))

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_lever("affirm")

        assert len(results) == 25
        assert results[-1]["title"] == "Role 24"


class TestSearchAshby:
    async def test_returns_full_board_by_default(self):
        jobs = [
            {
                "id": f"ashby-{index}",
                "title": f"Role {index}",
                "jobUrl": f"https://example.com/{index}",
                "descriptionPlain": f"Description {index}",
                "location": "Remote",
                "department": "Engineering",
                "publishedAt": "2026-03-18",
            }
            for index in range(25)
        ]
        mock_client = _mock_client_with(
            _mock_httpx_response({"organizationName": "Affirm", "jobs": jobs})
        )

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_ashby("affirm")

        assert len(results) == 25
        assert results[-1]["title"] == "Role 24"


class TestSearchWorkable:
    async def test_fetches_exact_job_from_public_endpoint(self):
        job_response = _mock_httpx_response(
            {
                "id": 5128536,
                "shortcode": "11DC4EA360",
                "title": "Software Engineer - Early Career (USA)",
                "remote": False,
                "location": {
                    "country": "United States",
                    "city": "Stamford",
                    "region": "Connecticut",
                },
                "locations": [],
                "published": "2025-09-09T00:00:00.000Z",
                "type": "full",
                "department": ["Technology"],
                "workplace": "on_site",
                "description": "<p>Build systems</p>",
            }
        )
        account_response = _mock_httpx_response({"name": "Trexquant Investment"})
        mock_client = _mock_client_with(job_response)
        mock_client.get = AsyncMock(side_effect=[job_response, account_response])

        with patch("app.clients.ats_client.httpx.AsyncClient", return_value=mock_client):
            results = await search_workable("trexquant", job_shortcode="AC6E22F084")

        assert len(results) == 1
        assert results[0]["external_id"] == "wk_11DC4EA360"
        assert results[0]["company_name"] == "Trexquant Investment"
        assert results[0]["url"] == "https://apply.workable.com/trexquant/j/11DC4EA360"
        assert results[0]["location"] == "Stamford, Connecticut, United States"
        assert results[0]["department"] == "Technology"


class TestParseATSJobURL:
    def test_parses_greenhouse_canonical_url(self):
        parsed = parse_ats_job_url("https://job-boards.greenhouse.io/affirm/jobs/7550577003")
        assert parsed is not None
        assert parsed.ats_type == "greenhouse"
        assert parsed.company_slug == "affirm"
        assert parsed.external_id == "gh_7550577003"

    def test_parses_greenhouse_embed_url(self):
        parsed = parse_ats_job_url(
            "https://job-boards.greenhouse.io/embed/job_app?for=affirm&jr_id=foo&token=7550577003"
        )
        assert parsed is not None
        assert parsed.ats_type == "greenhouse"
        assert parsed.company_slug == "affirm"
        assert parsed.external_id == "gh_7550577003"
        assert parsed.canonical_url == "https://job-boards.greenhouse.io/affirm/jobs/7550577003"

    def test_parses_lever_url(self):
        parsed = parse_ats_job_url("https://jobs.lever.co/stripe/abc123")
        assert parsed is not None
        assert parsed.ats_type == "lever"
        assert parsed.company_slug == "stripe"
        assert parsed.external_id == "lv_abc123"

    def test_parses_ashby_url(self):
        parsed = parse_ats_job_url("https://jobs.ashbyhq.com/notion/1234")
        assert parsed is not None
        assert parsed.ats_type == "ashby"
        assert parsed.company_slug == "notion"
        assert parsed.external_id == "ab_1234"

    def test_parses_workable_url(self):
        parsed = parse_ats_job_url("https://apply.workable.com/trexquant/j/AC6E22F084/?jr_id=68c040328e65e77df55bf6c3")
        assert parsed is not None
        assert parsed.ats_type == "workable"
        assert parsed.company_slug == "trexquant"
        assert parsed.external_id == "wk_AC6E22F084"
        assert parsed.canonical_url == "https://apply.workable.com/trexquant/j/AC6E22F084"

    def test_parses_apple_jobs_url(self):
        parsed = parse_ats_job_url(
            "https://jobs.apple.com/en-us/details/200652765/software-engineer-core-os-telemetry?board_id=17682&jr_id=69bdc46c393a1008f7434e68"
        )
        assert parsed is not None
        assert parsed.ats_type == "apple_jobs"
        assert parsed.company_slug == "apple"
        assert parsed.external_id == "apple_200652765"
        assert parsed.canonical_url == (
            "https://jobs.apple.com/en-us/details/200652765/software-engineer-core-os-telemetry"
        )
        assert parsed.exact_url_only is True

    def test_parses_workday_url(self):
        parsed = parse_ats_job_url(
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
            "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
            "?jr_id=69bd8442b106024562826cc8"
        )
        assert parsed is not None
        assert parsed.ats_type == "workday"
        assert parsed.company_slug == "nvidia"
        assert parsed.external_id == "wd_JR2015144-1"
        assert parsed.canonical_url == (
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
            "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
        )
        assert parsed.exact_url_only is True

    def test_parses_generic_exact_job_url(self):
        parsed = parse_ats_job_url("https://careers.example.com/jobs/platform-engineer?utm_source=test")
        assert parsed is not None
        assert parsed.ats_type == "generic_exact"
        assert parsed.company_slug == "example"
        assert parsed.canonical_url == "https://careers.example.com/jobs/platform-engineer"
        assert parsed.exact_url_only is True


class TestFetchExactJob:
    async def test_fetches_apple_job_from_hydration_payload(self):
        parsed = parse_ats_job_url(
            "https://jobs.apple.com/en-us/details/200652765/software-engineer-core-os-telemetry"
        )
        assert parsed is not None

        payload = {
            "loaderData": {
                "jobDetails": {
                    "jobsData": {
                        "jobNumber": "200652765",
                        "postingTitle": "Software Engineer - Core OS Telemetry",
                        "jobSummary": "Build telemetry systems.",
                        "description": "You will work on Core OS telemetry.",
                        "responsibilities": "<ul><li>Ship backend services</li></ul>",
                        "minimumQualifications": "<ul><li>BS in CS</li></ul>",
                        "preferredQualifications": "<ul><li>Swift or Python</li></ul>",
                        "locations": [
                            {
                                "city": "Cupertino",
                                "stateProvince": "California",
                                "countryName": "United States",
                            }
                        ],
                        "teamNames": ["Core OS"],
                        "employmentType": "Full Time",
                        "postDateInGMT": "2026-03-21T00:00:00Z",
                    }
                }
            }
        }
        escaped_payload = json.dumps(json.dumps(payload))[1:-1]
        page = {
            "url": parsed.canonical_url,
            "title": "Software Engineer - Core OS Telemetry - Jobs - Careers at Apple",
            "html": (
                "<html><body><script>"
                f'window.__staticRouterHydrationData = JSON.parse("{escaped_payload}");'
                "</script></body></html>"
            ),
            "content": "",
        }

        with patch(
            "app.clients.ats_client._fetch_exact_page_candidates",
            new_callable=AsyncMock,
        ) as mock_fetch_page_candidates:
            mock_fetch_page_candidates.return_value = [page]
            jobs = await fetch_exact_job(parsed)

        assert len(jobs) == 1
        assert jobs[0]["ats"] == "apple_jobs"
        assert jobs[0]["title"] == "Software Engineer - Core OS Telemetry"
        assert jobs[0]["company_name"] == "Apple"
        assert jobs[0]["location"] == "Cupertino, California, United States"
        assert jobs[0]["department"] == "Core OS"
        assert "Minimum Qualifications" in (jobs[0]["description"] or "")

    async def test_fetches_generic_exact_job_from_json_ld(self):
        parsed = parse_ats_job_url("https://careers.example.com/jobs/platform-engineer")
        assert parsed is not None

        page = {
            "url": parsed.canonical_url,
            "title": "Platform Engineer - Example",
            "html": """
                <html><head>
                <script type="application/ld+json">
                {
                  "@context":"https://schema.org",
                  "@type":"JobPosting",
                  "title":"Platform Engineer",
                  "description":"Build platform systems.",
                  "employmentType":"FULL_TIME",
                  "datePosted":"2026-03-20",
                  "hiringOrganization":{"name":"Example"},
                  "jobLocation":{
                    "@type":"Place",
                    "address":{
                      "@type":"PostalAddress",
                      "addressLocality":"Toronto",
                      "addressRegion":"ON",
                      "addressCountry":"CA"
                    }
                  }
                }
                </script>
                </head><body></body></html>
            """,
            "content": "",
        }

        with patch(
            "app.clients.ats_client._fetch_exact_page_candidates",
            new_callable=AsyncMock,
        ) as mock_fetch_page_candidates:
            mock_fetch_page_candidates.return_value = [page]
            jobs = await fetch_exact_job(parsed)

        assert len(jobs) == 1
        assert jobs[0]["ats"] == "example_jobs"
        assert jobs[0]["company_name"] == "Example"
        assert jobs[0]["location"] == "Toronto, ON, CA"
        assert jobs[0]["source"] == "example_jobs"

    async def test_fetches_workday_job_from_json_ld(self):
        parsed = parse_ats_job_url(
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
            "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
        )
        assert parsed is not None

        page = {
            "url": parsed.canonical_url,
            "title": "",
            "html": """
                <html>
                  <head>
                    <link rel="canonical" href="https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1" />
                    <meta property="og:title" content="Senior Systems Software Engineer - New College Grad 2026" />
                    <meta property="og:description" content="Build software systems." />
                    <script type="application/ld+json">
                    {
                      "@context":"https://schema.org",
                      "@type":"JobPosting",
                      "title":"Senior Systems Software Engineer - New College Grad 2026",
                      "description":"Build software systems.",
                      "employmentType":"FULL_TIME",
                      "datePosted":"2026-03-20",
                      "identifier":{"@type":"PropertyValue","value":"JR2015144"},
                      "hiringOrganization":{"@type":"Organization","name":"2100 NVIDIA USA"},
                      "jobLocation":{
                        "@type":"Place",
                        "address":{
                          "@type":"PostalAddress",
                          "addressCountry":"United States of America",
                          "addressLocality":"US, OR, Hillsboro"
                        }
                      }
                    }
                    </script>
                  </head>
                  <body></body>
                </html>
            """,
            "content": "",
        }

        with patch(
            "app.clients.ats_client._fetch_exact_page_candidates",
            new_callable=AsyncMock,
        ) as mock_fetch_page_candidates:
            mock_fetch_page_candidates.return_value = [page]
            jobs = await fetch_exact_job(parsed)

        assert len(jobs) == 1
        assert jobs[0]["ats"] == "workday"
        assert jobs[0]["title"] == "Senior Systems Software Engineer - New College Grad 2026"
        assert jobs[0]["company_name"] == "NVIDIA"
        assert jobs[0]["location"] == "Hillsboro, OR, United States"
        assert jobs[0]["url"] == (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/"
            "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
        )

    async def test_fetches_workday_job_preserves_distinguishing_brand_tokens(self):
        parsed = parse_ats_job_url(
            "https://fortune.wd108.myworkdayjobs.com/en-US/Fortune/job/New-York-City/"
            "Full-Stack-Software-Engineer-Nextjs_JR100020"
        )
        assert parsed is not None

        page = {
            "url": parsed.canonical_url,
            "title": "",
            "html": """
                <html>
                  <head>
                    <link rel="canonical" href="https://fortune.wd108.myworkdayjobs.com/en-US/Fortune/job/Full-Stack-Software-Engineer-Nextjs_JR100020" />
                    <script type="application/ld+json">
                    {
                      "@context":"https://schema.org",
                      "@type":"JobPosting",
                      "title":"Full Stack Software Engineer Next.js",
                      "description":"At Fortune Media, we are reinventing digital business journalism.",
                      "employmentType":"FULL_TIME",
                      "datePosted":"2026-03-20",
                      "identifier":{"@type":"PropertyValue","value":"JR100020"},
                      "hiringOrganization":{"@type":"Organization","name":"Fortune Media (USA) Corporation"},
                      "jobLocation":{
                        "@type":"Place",
                        "address":{
                          "@type":"PostalAddress",
                          "addressCountry":"United States of America",
                          "addressLocality":"New York City"
                        }
                      }
                    }
                    </script>
                  </head>
                  <body></body>
                </html>
            """,
            "content": "",
        }

        with patch(
            "app.clients.ats_client._fetch_exact_page_candidates",
            new_callable=AsyncMock,
        ) as mock_fetch_page_candidates:
            mock_fetch_page_candidates.return_value = [page]
            jobs = await fetch_exact_job(parsed)

        assert len(jobs) == 1
        assert jobs[0]["company_name"] == "Fortune Media"
        assert jobs[0]["ats_slug"] == "fortune"

    async def test_workday_fetch_rejects_redirected_careers_page(self):
        parsed = parse_ats_job_url(
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-OR-Hillsboro/"
            "Senior-Systems-Software-Engineer---New-College-Grad-2026_JR2015144-1"
        )
        assert parsed is not None

        page = {
            "url": "https://www.nvidia.com/en-us/about-nvidia/careers/",
            "title": "Jobs at NVIDIA | NVIDIA Careers",
            "html": """
                <html>
                  <head>
                    <link rel="canonical" href="https://www.nvidia.com/en-us/about-nvidia/careers/" />
                    <meta property="og:title" content="Like no Place You've Ever Worked" />
                    <meta property="og:description" content="Nvidia careers jobs" />
                  </head>
                  <body></body>
                </html>
            """,
            "content": "Nvidia careers jobs",
        }

        with (
            patch(
                "app.clients.ats_client._probe_workday_job_redirect",
                new_callable=AsyncMock,
            ) as mock_probe_redirect,
            patch(
                "app.clients.ats_client._fetch_exact_page_candidates",
                new_callable=AsyncMock,
            ) as mock_fetch_page_candidates,
        ):
            mock_probe_redirect.return_value = "outage"
            mock_fetch_page_candidates.return_value = [page]
            with pytest.raises(
                ExactJobFetchError,
                match="Workday is currently unavailable for this job posting.",
            ):
                await fetch_exact_job(parsed)

    async def test_fetch_exact_job_raises_when_page_lacks_required_metadata(self):
        parsed = parse_ats_job_url("https://careers.example.com/jobs/platform-engineer")
        assert parsed is not None

        page = {
            "url": parsed.canonical_url,
            "title": "",
            "html": "<html><body><p>No useful metadata</p></body></html>",
            "content": "",
        }

        with patch(
            "app.clients.ats_client._fetch_exact_page_candidates",
            new_callable=AsyncMock,
        ) as mock_fetch_page_candidates:
            mock_fetch_page_candidates.return_value = [page]
            with pytest.raises(ExactJobFetchError):
                await fetch_exact_job(parsed)
