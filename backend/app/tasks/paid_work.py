"""Recover paid-work reservations abandoned by crashed request/task workers."""

from app.services.paid_work import recover_expired
from app.tasks import celery_app, run_async


@celery_app.task(name="app.tasks.paid_work.recover_expired")
def recover_expired_paid_work() -> dict[str, int]:
    return run_async(recover_expired())
