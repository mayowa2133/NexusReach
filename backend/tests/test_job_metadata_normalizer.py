"""Regression tests for centralized job metadata normalization."""

import pytest

from app.utils.job_metadata import (
    SOURCE_QUALITY_MATRIX,
    geocode_location_query,
    normalize_job_metadata,
    parse_json_ld_base_salary,
    parse_salary_from_text,
)


def test_normalize_locations_country_and_remote_work_mode() -> None:
    job = normalize_job_metadata({
        "title": "Founding Product Engineer",
        "company_name": "Cartesia",
        "location": "Remote (US)",
        "remote": True,
        "source": "yc_jobs",
        "min_experience": 2,
    })

    assert job["work_mode"] == "remote"
    assert job["remote"] is True
    assert job["countries"] == ["United States"]
    assert job["country_codes"] == ["US"]
    assert job["locations"][0]["country_code"] == "US"


def test_normalize_locations_geocodes_toronto_and_gta() -> None:
    toronto = normalize_job_metadata({
        "title": "Backend Engineer",
        "company_name": "Shopify",
        "location": "Toronto, ON, CA",
        "source": "greenhouse",
    })
    gta = geocode_location_query("GTA")

    assert toronto["location_lat"] == pytest.approx(43.6532, abs=0.001)
    assert toronto["location_lng"] == pytest.approx(-79.3832, abs=0.001)
    assert toronto["location_geocode_label"] == "Toronto, ON, Canada"
    assert toronto["country_codes"] == ["CA"]
    assert gta is not None
    assert gta.label == "Greater Toronto Area, ON, Canada"
    assert gta.radius_km == 60


def test_level_classifier_uses_source_labels_years_and_roman_numerals() -> None:
    assert normalize_job_metadata({
        "title": "Senior Systems Software Engineer - New College Grad 2026",
        "source": "workday",
        "description": "0-2 years of experience.",
    })["experience_level"] == "new_grad"

    assert normalize_job_metadata({
        "title": "Software Engineer IV",
        "source": "greenhouse",
    })["experience_level"] == "senior"

    assert normalize_job_metadata({
        "title": "Backend Engineer",
        "source": "yc_jobs",
        "minExperience": 1,
    })["experience_level"] == "new_grad"


def test_salary_from_source_text_and_description() -> None:
    source_salary = parse_salary_from_text("$150K/yr - $190K/yr", source="fixture")
    assert source_salary is not None
    assert source_salary.minimum == 150000
    assert source_salary.maximum == 190000
    assert source_salary.currency == "USD"
    assert source_salary.period == "year"

    job = normalize_job_metadata({
        "title": "Backend Engineer",
        "company_name": "Example",
        "source": "remotive",
        "salary": "$80,000 - $120,000 USD / year",
        "description": "Build APIs.",
    })

    assert job["salary_min"] == 80000
    assert job["salary_max"] == 120000
    assert job["salary_currency"] == "USD"
    assert job["salary_period"] == "year"
    assert job["metadata_provenance"]["salary"]["source"] == "source_text"


def test_json_ld_salary_parser() -> None:
    parsed = parse_json_ld_base_salary({
        "@type": "MonetaryAmount",
        "currency": "USD",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 45,
            "maxValue": 65,
            "unitText": "HOUR",
        },
    })

    assert parsed is not None
    assert parsed.minimum == 45
    assert parsed.maximum == 65
    assert parsed.currency == "USD"
    assert parsed.period == "hour"


def test_source_quality_matrix_covers_major_sources() -> None:
    for source in (
        "newgrad_jobs",
        "yc_jobs",
        "jsearch",
        "adzuna",
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "workable",
        "google_careers",
        "microsoft",
    ):
        assert {"location", "salary", "level", "description"} <= set(SOURCE_QUALITY_MATRIX[source])


@pytest.mark.parametrize(
    ("raw_job", "expected"),
    [
        (
            {
                "title": "Associate Software Engineer",
                "company_name": "U.S. Bank",
                "location": "Minneapolis, MN",
                "remote": False,
                "employment_type": "full-time",
                "salary": "$93,000 - $109,000 USD / year",
                "description": "Entry Level role. Build backend services with Python.",
                "source": "newgrad_jobs",
                "level_label": "Entry Level",
            },
            {
                "level": "new_grad",
                "salary_min": 93000,
                "country_codes": ["US"],
                "employment_type": "full-time",
                "work_mode": None,
            },
        ),
        (
            {
                "title": "Founding Product Engineer",
                "company_name": "Cartesia",
                "location": "Remote (US)",
                "remote": True,
                "employment_type": "Full-time",
                "salary_min": 150000,
                "salary_max": 190000,
                "salary_currency": "USD",
                "description": "Skills: React, TypeScript. Experience: 2+ years",
                "source": "yc_jobs",
                "minExperience": 2,
            },
            {
                "level": "new_grad",
                "salary_min": 150000,
                "country_codes": ["US"],
                "employment_type": "full-time",
                "work_mode": "remote",
            },
        ),
        (
            {
                "title": "Software Engineer IV",
                "company_name": "Example",
                "location": "Toronto, ON, Canada",
                "remote": False,
                "employment_type": "FULL_TIME",
                "description": "Compensation: CAD 180,000 - 220,000 per year. Requirements: Go.",
                "source": "greenhouse",
            },
            {
                "level": "senior",
                "salary_min": 180000,
                "country_codes": ["CA"],
                "employment_type": "full-time",
                "work_mode": None,
            },
        ),
        (
            {
                "title": "Backend Engineer",
                "company_name": "RemoteCo",
                "location": "Remote - Europe",
                "remote": True,
                "employment_type": "contract",
                "description": "Requirements: Python, PostgreSQL.",
                "salary": "€70,000 - €95,000 annually",
                "source": "remotive",
            },
            {
                "level": "mid",
                "salary_min": 70000,
                "country_codes": None,
                "employment_type": "contract",
                "work_mode": "remote",
            },
        ),
    ],
)
def test_source_fixture_regressions(raw_job: dict, expected: dict) -> None:
    normalized = normalize_job_metadata(raw_job)

    assert normalized["experience_level"] == expected["level"]
    assert normalized["salary_min"] == expected["salary_min"]
    assert normalized["country_codes"] == expected["country_codes"]
    assert normalized["employment_type"] == expected["employment_type"]
    assert normalized["work_mode"] == expected["work_mode"]
    assert normalized["description"]
    assert normalized["metadata_provenance"]["source_quality"]


def test_normalize_clamps_oversized_string_fields_to_column_widths():
    """One oversized value fails the whole INSERT batch with
    StringDataRightTruncationError (Sentry PYTHON-15) — normalization must
    truncate free-text fields to their jobs-table column widths."""
    from app.utils.job_metadata import JOB_STRING_FIELD_LIMITS, normalize_job_metadata

    normalized = normalize_job_metadata(
        {
            "title": "Engineer " * 100,                    # 500 cap
            "company_name": "A" * 400,                     # 255 cap
            "location": "New York, NY; " + "x" * 300,      # 255 cap
            "external_id": "id-" + "9" * 400,              # 255 cap
            "url": "https://example.com/" + "p" * 1200,    # 1000 cap
            "posted_at": "posted a very long time ago " * 5,  # 50 cap
            "source": "jsearch",
        }
    )

    for field in ("title", "company_name", "location", "external_id", "url", "posted_at"):
        assert len(normalized[field]) <= JOB_STRING_FIELD_LIMITS[field], field
    assert normalized["company_name"] == "A" * 255
    # Short values and non-strings pass through untouched.
    assert normalized["source"] == "jsearch"


def test_clamp_limits_match_job_model_columns():
    """The clamp map must stay in sync with the actual column widths."""
    from sqlalchemy import String

    from app.models.job import Job
    from app.utils.job_metadata import JOB_STRING_FIELD_LIMITS

    for field, max_len in JOB_STRING_FIELD_LIMITS.items():
        column_type = Job.__table__.columns[field].type
        assert isinstance(column_type, String), field
        assert column_type.length == max_len, (
            f"{field}: clamp {max_len} != column {column_type.length}"
        )
