"""Tests for job experience-level inference."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.job_service import _build_job, get_jobs
from app.utils.experience_level import (
    classify_experience_level,
    classify_experience_level_for_job,
    classify_experience_level_metadata,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineering Student Program", "intern"),
        ("Data Science Student Researcher", "intern"),
        ("2026 Summer Analyst", "intern"),
        ("Software Engineer - Summer 2026", "intern"),
        ("Industrial Placement Software Engineer", "intern"),
        ("Student Success Manager", "mid"),
        ("University Recruiting Program Manager", "mid"),
    ],
)
def test_classify_experience_level_handles_student_internship_wording(
    title: str,
    expected: str,
) -> None:
    assert classify_experience_level(title) == expected


def test_newgrad_source_uses_level_label_for_student_programs() -> None:
    assert (
        classify_experience_level_for_job(
            "Software Engineer",
            source="newgrad_jobs",
            level_label="Student Program",
        )
        == "intern"
    )


def test_classifier_prefers_new_college_grad_over_senior_wording() -> None:
    result = classify_experience_level_metadata(
        "Senior Systems Software Engineer - New College Grad 2026",
        description="0-2 years of experience.",
    )

    assert result.level == "new_grad"
    assert result.confidence >= 0.8


def test_classifier_does_not_make_product_manager_senior() -> None:
    result = classify_experience_level_metadata("Product Manager")

    assert result.level == "mid"
    assert result.source == "default"


def test_classifier_uses_years_and_roman_numerals() -> None:
    assert classify_experience_level_metadata("Software Engineer IV").level == "senior"
    assert (
        classify_experience_level_metadata(
            "Backend Engineer",
            description="Minimum qualifications: 1+ years of experience with APIs.",
        ).level
        == "new_grad"
    )
    assert (
        classify_experience_level_metadata(
            "Backend Engineer",
            description="Minimum qualifications: 6+ years of experience building APIs.",
        ).level
        == "senior"
    )


def test_build_job_marks_inferred_interns_as_internship_type() -> None:
    job = _build_job(
        user_id=uuid.uuid4(),
        data={
            "title": "Software Engineering Student Program",
            "company_name": "Example",
            "source": "jsearch",
        },
        score=50.0,
        breakdown={},
        fingerprint="example",
    )

    assert job.experience_level == "intern"
    assert job.employment_type == "internship"


@pytest.mark.asyncio
async def test_internship_type_filter_includes_inferred_interns() -> None:
    db = MagicMock()

    with (
        patch(
            "app.utils.pagination.paginate",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_paginate,
        patch(
            "app.services.jobs.search._repair_missing_apply_urls",
            new_callable=AsyncMock,
        ),
    ):
        jobs, total = await get_jobs(
            db,
            uuid.uuid4(),
            employment_type="internship",
        )

    assert jobs == []
    assert total == 0
    query = mock_paginate.await_args.args[1]
    compiled_query = str(query)
    assert "lower(jobs.employment_type)" in compiled_query
    assert "jobs.experience_level" in compiled_query


@pytest.mark.asyncio
async def test_country_filter_uses_structured_country_fields() -> None:
    db = MagicMock()

    with (
        patch(
            "app.utils.pagination.paginate",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_paginate,
        patch(
            "app.services.jobs.search._repair_missing_apply_urls",
            new_callable=AsyncMock,
        ),
    ):
        jobs, total = await get_jobs(
            db,
            uuid.uuid4(),
            country="Canada",
        )

    assert jobs == []
    assert total == 0
    query = mock_paginate.await_args.args[1]
    compiled_query = str(query)
    assert "jobs.country_codes" in compiled_query
    assert "jobs.countries" in compiled_query


@pytest.mark.asyncio
async def test_near_filter_uses_coordinate_radius() -> None:
    db = MagicMock()

    with (
        patch(
            "app.utils.pagination.paginate",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_paginate,
        patch(
            "app.services.jobs.search._repair_missing_apply_urls",
            new_callable=AsyncMock,
        ),
    ):
        jobs, total = await get_jobs(
            db,
            uuid.uuid4(),
            near="GTA",
            radius_km=50,
            sort_by="distance",
        )

    assert jobs == []
    assert total == 0
    query = mock_paginate.await_args.args[1]
    compiled_query = str(query)
    assert "jobs.location_lat IS NOT NULL" in compiled_query
    assert "jobs.location_lng IS NOT NULL" in compiled_query
    assert "acos" in compiled_query


@pytest.mark.asyncio
async def test_near_filter_can_include_remote_jobs() -> None:
    db = MagicMock()

    with (
        patch(
            "app.utils.pagination.paginate",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_paginate,
        patch(
            "app.services.jobs.search._repair_missing_apply_urls",
            new_callable=AsyncMock,
        ),
    ):
        await get_jobs(
            db,
            uuid.uuid4(),
            near_lat=43.6532,
            near_lng=-79.3832,
            radius_km=50,
            include_remote_in_radius=True,
        )

    query = mock_paginate.await_args.args[1]
    compiled_query = str(query)
    assert "jobs.remote IS true" in compiled_query
