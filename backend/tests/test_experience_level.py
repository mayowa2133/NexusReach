"""Tests for job experience-level inference."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.job_service import _build_job, get_jobs
from app.utils.experience_level import (
    classify_experience_level,
    classify_experience_level_for_job,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Software Engineering Student Program", "intern"),
        ("Data Science Student Researcher", "intern"),
        ("2026 Summer Analyst", "intern"),
        ("Software Engineer - Summer 2026", "intern"),
        ("Industrial Placement Software Engineer", "intern"),
        ("Student Success Manager", "senior"),
        ("University Recruiting Program Manager", "senior"),
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
            "app.services.job_service._repair_missing_apply_urls",
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
