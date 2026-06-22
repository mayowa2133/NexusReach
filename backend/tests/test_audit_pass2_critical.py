"""Proof tests for audit pass-2 CRITICAL/related fixes (P1, P2/P5, P3, P7, P9).

DB-atomic behaviors (P1 serializer no-crash, P2 concurrent-claim) are additionally
proven by live Postgres reproductions during the fix; these lock in the logic.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# P3 — date sort can't crash on invalid calendar dates
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-05-21T00:00:00Z", (2026, 5, 21)),
        ("2026-05-21", (2026, 5, 21)),
        ("2026-02-30", None),  # date-shaped but invalid -> None (was the crash trigger)
        ("2026-13-01", None),
        ("0000-00-00", None),
        # Relative phrases now resolve to a real day (see test_posting_time.py);
        # only genuinely unparseable / invalid values must still return None.
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_p3_parse_posted_date_rejects_invalid(value, expected):
    from app.services.job_service import _parse_posted_date

    result = _parse_posted_date(value)
    if expected is None:
        assert result is None
    else:
        from datetime import date

        assert result == date(*expected)


def test_p3_order_by_uses_validated_column_not_runtime_cast():
    """The date sort must order by the pre-parsed posted_date column, never cast
    a substring of the free-form posted_at string at query time."""
    import inspect

    from app.services import job_service

    src = inspect.getsource(job_service.get_jobs)
    assert "Job.posted_date" in src
    # The old crash-prone runtime cast of a posted_at substring must be gone.
    assert "substring(Job.posted_at" not in src


# ---------------------------------------------------------------------------
# P7 — refresh must not wipe work_mode to NULL
# ---------------------------------------------------------------------------
def test_p7_refresh_preserves_work_mode_when_omitted():
    from app.models.job import Job
    from app.services.job_service import _refresh_existing_job

    job = Job(title="SWE", company_name="Acme", source="greenhouse", work_mode="hybrid")
    _refresh_existing_job(
        job,
        {"title": "SWE", "company_name": "Acme", "source": "greenhouse"},  # no work_mode
        fingerprint="fp",
        score=None,
        breakdown={},
        experience_level="mid",
    )
    assert job.work_mode == "hybrid"


def test_p7_refresh_updates_work_mode_when_provided():
    from app.models.job import Job
    from app.services.job_service import _refresh_existing_job

    job = Job(title="SWE", company_name="Acme", source="greenhouse", work_mode="hybrid")
    _refresh_existing_job(
        job,
        {"title": "SWE", "company_name": "Acme", "source": "greenhouse", "work_mode": "remote"},
        fingerprint="fp",
        score=None,
        breakdown={},
        experience_level="mid",
    )
    assert job.work_mode == "remote"


# ---------------------------------------------------------------------------
# P9 — outreach rejects cross-user job_id / message_id
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p9_assert_owned_references_rejects_foreign_job():
    from app.services.outreach_service import _assert_owned_references

    db = MagicMock()
    # Simulate "job not owned by user" -> scalar_one_or_none() returns None.
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(ValueError, match="Job not found"):
        await _assert_owned_references(
            db, uuid.uuid4(), job_id=uuid.uuid4(), message_id=None
        )


@pytest.mark.asyncio
async def test_p9_assert_owned_references_allows_owned():
    from app.services.outreach_service import _assert_owned_references

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())  # found -> owned
    db.execute = AsyncMock(return_value=result)
    # Should not raise.
    await _assert_owned_references(db, uuid.uuid4(), job_id=uuid.uuid4(), message_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# P1 — outreach loaders eager-load serializer relationships
# ---------------------------------------------------------------------------
def test_p1_loaders_eager_load_person_company_and_job():
    import inspect

    from app.services import outreach_service

    src = inspect.getsource(outreach_service)
    # The shared options load person.company and job.
    assert "selectinload(OutreachLog.person).selectinload(Person.company)" in src
    assert "selectinload(OutreachLog.job)" in src
    # All three read paths + create/update use the shared options / reload.
    assert src.count("_outreach_load_options()") >= 3


# ---------------------------------------------------------------------------
# P2/P5 — atomic claim contract
# ---------------------------------------------------------------------------
def test_p2_claim_is_atomic_staged_to_sending():
    import inspect

    from app.services import draft_staging_service

    src = inspect.getsource(draft_staging_service.claim_message_for_send)
    # Single UPDATE gated on status='staged', transitioning to 'sending'.
    assert 'Message.status == "staged"' in src
    assert 'status="sending"' in src
    assert "rowcount" in src
