"""Tests for the occupation tag backfill service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.occupation_backfill_service import (
    BATCH_SIZE,
    backfill_occupation_tags,
)
from app.services.occupation_taxonomy import OCCUPATION_TAG_PREFIX


@dataclass
class _FakeJob:
    id: str
    title: str
    description: str | None = None
    tags: list[str] | None = None


class _FakeResult:
    def __init__(self, rows: list[_FakeJob]):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


@dataclass
class _FakeStmt:
    rows: list[_FakeJob] = field(default_factory=list)
    where_user_id: Any = None
    limit_value: int | None = None

    def where(self, *_):
        return self

    def order_by(self, *_):
        return self

    def limit(self, value):
        self.limit_value = value
        return self


class _FakeSession:
    def __init__(self, jobs: list[_FakeJob]):
        self.jobs = jobs
        self.commits = 0

    async def execute(self, _stmt):
        return _FakeResult(self.jobs)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_backfill_tags_a_clean_job_and_skips_already_tagged_one() -> None:
    jobs = [
        _FakeJob(id="a", title="Senior Backend Engineer", tags=None),
        _FakeJob(
            id="b",
            title="Account Executive",
            tags=[f"{OCCUPATION_TAG_PREFIX}sales"],
        ),
        _FakeJob(id="c", title="HR Business Partner", tags=["startup"]),
        _FakeJob(id="d", title="Some Off-the-wall Title", tags=None),
    ]
    db = _FakeSession(jobs)

    counters = await backfill_occupation_tags(db)  # type: ignore[arg-type]

    assert counters["scanned"] == 4
    assert counters["tagged"] == 2
    assert counters["already_tagged"] == 1
    assert counters["unclassified"] == 1
    assert counters["errors"] == 0
    assert jobs[0].tags == [f"{OCCUPATION_TAG_PREFIX}software_engineering"]
    # job b is already tagged — untouched
    assert jobs[1].tags == [f"{OCCUPATION_TAG_PREFIX}sales"]
    # job c had a non-occupation tag — backfill should preserve it and add the HR tag
    assert "startup" in (jobs[2].tags or [])
    assert f"{OCCUPATION_TAG_PREFIX}human_resources" in (jobs[2].tags or [])
    # job d couldn't be classified — left alone
    assert jobs[3].tags is None
    # one commit at the end (no batches reached)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_dry_run_leaves_db_untouched() -> None:
    jobs = [_FakeJob(id="a", title="Marketing Manager", tags=None)]
    db = _FakeSession(jobs)

    counters = await backfill_occupation_tags(db, dry_run=True)  # type: ignore[arg-type]

    assert counters["tagged"] == 1
    assert jobs[0].tags is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_batch_size_constant_is_positive() -> None:
    assert BATCH_SIZE > 0
