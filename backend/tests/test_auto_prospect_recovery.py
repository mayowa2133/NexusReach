"""Recovery for pre-warms that never completed (functionality audit #9).

`prewarm_job_people_batch` always flips a job to `ready` — even on failure or
zero results — and the enqueue path un-sticks jobs whose `.delay()` raised. So a
job left in `pending` means the task reached the broker and then died. Nothing
retried those: the audit found 15 pending for ~7 days, visible in the feed with
no people behind them.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.tasks import auto_prospect as ap


def test_thresholds_never_race_a_running_warm():
    """Recovery must sit well past the reveal timeout, or it double-queues."""
    from app.services.jobs.command_center import PEOPLE_PREWARM_REVEAL_TIMEOUT

    assert ap._PREWARM_STUCK_AFTER > PEOPLE_PREWARM_REVEAL_TIMEOUT
    assert ap._PREWARM_GIVE_UP_AFTER > ap._PREWARM_STUCK_AFTER


def _db_with(rows, retired=0):
    db = AsyncMock()
    retire_result = MagicMock()
    retire_result.rowcount = retired
    select_result = MagicMock()
    select_result.all.return_value = rows
    db.execute.side_effect = [retire_result, select_result]
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


async def test_stuck_jobs_are_requeued():
    import uuid

    user = uuid.uuid4()
    rows = [(uuid.uuid4(), user), (uuid.uuid4(), user)]
    db = _db_with(rows)

    with (
        patch.object(ap, "async_session", return_value=db),
        patch.object(ap.prewarm_job_people_batch, "delay") as delay,
    ):
        result = await ap._recover_stuck_prewarms()

    assert result["requeued"] == 2
    delay.assert_called_once()
    assert delay.call_args.args[0] == str(user)


async def test_long_dead_jobs_are_retired_not_retried_forever():
    db = _db_with([], retired=15)
    with (
        patch.object(ap, "async_session", return_value=db),
        patch.object(ap.prewarm_job_people_batch, "delay") as delay,
    ):
        result = await ap._recover_stuck_prewarms()

    assert result["retired"] == 15
    assert result["requeued"] == 0
    delay.assert_not_called()


async def test_nothing_stuck_is_a_no_op():
    db = _db_with([])
    with (
        patch.object(ap, "async_session", return_value=db),
        patch.object(ap.prewarm_job_people_batch, "delay") as delay,
    ):
        assert await ap._recover_stuck_prewarms() == {"requeued": 0, "retired": 0}
    delay.assert_not_called()


async def test_a_broker_failure_does_not_break_recovery():
    import uuid

    db = _db_with([(uuid.uuid4(), uuid.uuid4())])
    with (
        patch.object(ap, "async_session", return_value=db),
        patch.object(ap.prewarm_job_people_batch, "delay", side_effect=RuntimeError("broker down")),
    ):
        result = await ap._recover_stuck_prewarms()
    assert result["requeued"] == 0  # logged, not raised


def test_requeue_is_bounded():
    """A large backlog must not flood the prewarm queue in one tick."""
    assert 0 < ap._PREWARM_RECOVERY_MAX_JOBS <= 500
