"""Set-based dedup prefetch: the batch path must mirror the per-row probes.

``store_jobs`` prefetches every possible dedup match with a handful of IN
queries (``_prefetch_existing_jobs``) and resolves each raw job against the
in-memory ``_DedupIndex`` — the probe order (source+external_id, canonical
URL, legacy canonical backfill, fingerprint) must stay identical to the
per-row queries in ``_find_existing_job``.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.jobs import storage

pytestmark = pytest.mark.asyncio


def _job(**overrides) -> MagicMock:
    job = MagicMock()
    job.id = overrides.get("id", uuid.uuid4())
    job.source = overrides.get("source", "greenhouse")
    job.external_id = overrides.get("external_id", None)
    job.canonical_url = overrides.get("canonical_url", None)
    job.url = overrides.get("url", None)
    job.fingerprint = overrides.get("fingerprint", None)
    return job


def test_dedup_index_lookup_precedence():
    by_pair = _job(external_id="ext-1")
    by_url = _job(canonical_url="https://boards.example.com/acme/1")
    by_fp = _job(fingerprint="fp-1")

    index = storage._DedupIndex()
    index.by_source_external[("greenhouse", "ext-1")] = by_pair
    index.by_canonical["https://boards.example.com/acme/1"] = by_url
    index.by_fingerprint["fp-1"] = by_fp

    # source+external_id wins over URL and fingerprint.
    assert (
        index.lookup(
            source_key="greenhouse",
            external_id="ext-1",
            normalized_url="https://boards.example.com/acme/1",
            fingerprint="fp-1",
        )
        is by_pair
    )
    # Without the pair, canonical URL wins over fingerprint.
    assert (
        index.lookup(
            source_key="greenhouse",
            external_id="other",
            normalized_url="https://boards.example.com/acme/1",
            fingerprint="fp-1",
        )
        is by_url
    )
    # Fingerprint is the last resort.
    assert (
        index.lookup(
            source_key=None,
            external_id=None,
            normalized_url=None,
            fingerprint="fp-1",
        )
        is by_fp
    )
    assert (
        index.lookup(
            source_key=None, external_id=None, normalized_url=None, fingerprint="nope"
        )
        is None
    )


def test_dedup_index_legacy_match_backfills_canonical_url():
    """A legacy row (pre-canonical_url) match must backfill the column, exactly
    like the per-row legacy scan did."""
    legacy = _job(url="https://example.com/jobs/1?utm=x", canonical_url=None)
    index = storage._DedupIndex()
    index.legacy_by_canonical["https://example.com/jobs/1"] = legacy

    found = index.lookup(
        source_key=None,
        external_id=None,
        normalized_url="https://example.com/jobs/1",
        fingerprint=None,
    )
    assert found is legacy
    assert legacy.canonical_url == "https://example.com/jobs/1"


async def test_find_existing_job_with_index_runs_no_queries():
    """With a prefetched index the per-job lookup must not touch the DB."""
    job = _job(source="lever", external_id="ext-9")
    index = storage._DedupIndex()
    index.by_source_external[("lever", "ext-9")] = job

    db = MagicMock()
    db.execute = AsyncMock()

    found = await storage._find_existing_job(
        db,
        user_id=uuid.uuid4(),
        source="lever",
        ats=None,
        external_id="ext-9",
        url=None,
        fingerprint=None,
        index=index,
    )
    assert found is job
    db.execute.assert_not_awaited()

    missing = await storage._find_existing_job(
        db,
        user_id=uuid.uuid4(),
        source="lever",
        ats=None,
        external_id="unknown",
        url=None,
        fingerprint=None,
        index=index,
    )
    assert missing is None
    db.execute.assert_not_awaited()


class _ScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        rows = self._rows

        class _Scalars:
            def all(self):
                return rows

        return _Scalars()


async def test_prefetch_existing_jobs_builds_keep_first_maps():
    """Ordered results keep the earliest row per key, matching the per-row
    queries' ``ORDER BY created_at, id`` + first()."""
    first = _job(source="greenhouse", external_id="ext-1")
    later_duplicate = _job(source="greenhouse", external_id="ext-1")
    canonical = _job(canonical_url="https://example.com/jobs/2")
    legacy = _job(url="https://example.com/jobs/3?ref=feed", canonical_url=None)
    by_fp = _job(fingerprint="fp-3")

    # Query order in _prefetch_existing_jobs: pairs, canonical urls,
    # legacy scan (canonical_url IS NULL), fingerprints.
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarsResult([first, later_duplicate]),
            _ScalarsResult([canonical]),
            _ScalarsResult([legacy]),
            _ScalarsResult([by_fp]),
        ]
    )
    db.no_autoflush = MagicMock()
    db.no_autoflush.__enter__ = MagicMock(return_value=None)
    db.no_autoflush.__exit__ = MagicMock(return_value=False)

    prepared = [
        ({"source": "greenhouse", "external_id": "ext-1", "url": None}, "fp-1"),
        ({"source": None, "url": "https://example.com/jobs/2"}, "fp-2"),
        ({"source": None, "url": "https://example.com/jobs/3"}, "fp-3"),
    ]
    index = await storage._prefetch_existing_jobs(db, uuid.uuid4(), prepared)

    assert index.by_source_external[("greenhouse", "ext-1")] is first
    assert index.by_canonical["https://example.com/jobs/2"] is canonical
    assert index.legacy_by_canonical["https://example.com/jobs/3"] is legacy
    assert index.by_fingerprint["fp-3"] is by_fp
    assert db.execute.await_count == 4


async def test_store_raw_jobs_retries_on_concurrent_insert_conflict():
    """A concurrent discovery task can insert the same (user, ats, external_id)
    between our prefetch and commit (Sentry PYTHON-1B). The batch commit must
    catch the IntegrityError, roll back, and redo the resolve loop — the
    re-prefetch now sees the row, so the conflict becomes a refresh."""
    from sqlalchemy.exc import IntegrityError

    user_id = uuid.uuid4()
    raw = [
        {
            "source": "workday",
            "ats": "workday",
            "external_id": "wd-1",
            "company_name": "Acme",
            "title": "Engineer",
            "location": "NYC",
            "url": "https://acme.wd5.myworkdayjobs.com/1",
        }
    ]

    built = _job(source="workday", external_id="wd-1")
    existing = _job(source="workday", external_id="wd-1")

    db = MagicMock()
    db.add = MagicMock()
    db.rollback = AsyncMock()
    # First commit conflicts (another task inserted it), second succeeds.
    db.commit = AsyncMock(
        side_effect=[IntegrityError("INSERT", {}, Exception("dup")), None]
    )

    with (
        patch.object(storage, "_load_known_startup_company_names", new=AsyncMock(return_value=set())),
        patch.object(storage, "_infer_startup_tags_for_job"),
        patch.object(storage, "_infer_occupation_tags_for_job"),
        patch.object(storage, "normalize_job_metadata", side_effect=lambda d: d),
        patch.object(storage, "_prefetch_existing_jobs", new=AsyncMock(return_value=None)),
        # Attempt 1: not found -> insert -> conflict. Attempt 2: found -> refresh.
        patch.object(storage, "_find_existing_job", new=AsyncMock(side_effect=[None, existing])),
        patch.object(storage, "_score_job", return_value=(50.0, {})),
        patch.object(storage, "_build_job", return_value=built),
        patch.object(storage, "_refresh_existing_job"),
        patch.object(storage, "_maybe_auto_prospect", new=AsyncMock()),
        patch.object(storage, "_maybe_prewarm_people", new=AsyncMock()),
    ):
        result = await storage._store_raw_jobs(db, user_id, raw, None)

    assert db.rollback.await_count == 1
    assert db.commit.await_count == 2
    # On retry the row resolved to an existing refresh, so nothing new was stored.
    assert result == []


async def test_store_raw_jobs_gives_up_after_second_conflict_without_raising():
    """If a second concurrent insert hits the same window, the batch is dropped
    (data is safe — the constraint held) rather than crashing the discovery."""
    from sqlalchemy.exc import IntegrityError

    user_id = uuid.uuid4()
    raw = [
        {
            "source": "workday",
            "ats": "workday",
            "external_id": "wd-2",
            "company_name": "Globex",
            "title": "Analyst",
            "location": "Remote",
            "url": "https://globex.wd1.myworkdayjobs.com/2",
        }
    ]

    db = MagicMock()
    db.add = MagicMock()
    db.rollback = AsyncMock()
    db.commit = AsyncMock(
        side_effect=[
            IntegrityError("INSERT", {}, Exception("dup")),
            IntegrityError("INSERT", {}, Exception("dup")),
        ]
    )

    with (
        patch.object(storage, "_load_known_startup_company_names", new=AsyncMock(return_value=set())),
        patch.object(storage, "_infer_startup_tags_for_job"),
        patch.object(storage, "_infer_occupation_tags_for_job"),
        patch.object(storage, "normalize_job_metadata", side_effect=lambda d: d),
        patch.object(storage, "_prefetch_existing_jobs", new=AsyncMock(return_value=None)),
        patch.object(storage, "_find_existing_job", new=AsyncMock(return_value=None)),
        patch.object(storage, "_score_job", return_value=(50.0, {})),
        patch.object(storage, "_build_job", return_value=_job(source="workday", external_id="wd-2")),
        patch.object(storage, "_maybe_auto_prospect", new=AsyncMock()) as prospect,
        patch.object(storage, "_maybe_prewarm_people", new=AsyncMock()) as prewarm,
    ):
        result = await storage._store_raw_jobs(db, user_id, raw, None)

    assert result == []
    assert db.rollback.await_count == 2
    # No post-store side effects run when the batch is dropped.
    prospect.assert_not_awaited()
    prewarm.assert_not_awaited()
