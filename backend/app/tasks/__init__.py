"""Celery application and task registration."""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from typing import Any, TypeVar

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.observability import init_sentry

_T = TypeVar("_T")


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async coroutine from a synchronous Celery task safely (audit H12).

    The default prefork pool has no running event loop, so ``asyncio.run`` works.
    Under gevent/eventlet pools a loop may already be running, which makes
    ``asyncio.run`` raise "asyncio.run() cannot be called from a running event
    loop". In that case we execute the coroutine in a fresh loop on a worker
    thread so the task still completes regardless of the configured pool.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

init_sentry("worker")

celery_app = Celery(
    "nexusreach",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "refresh-job-feeds": {
            "task": "app.tasks.jobs.refresh_all_job_feeds",
            "schedule": crontab(minute="*/15"),  # every 15 minutes
        },
        "discover-ats-boards": {
            "task": "app.tasks.jobs.discover_ats_boards",
            "schedule": crontab(minute=7, hour="*/1"),  # hourly, offset from feed refresh
        },
        "reverify-stale-contacts": {
            "task": "app.tasks.reverify.reverify_stale_contacts",
            "schedule": crontab(minute=30, hour="*/6"),  # every 6 hours
        },
        "cleanup-orphaned-sync-sessions": {
            "task": "app.tasks.linkedin_graph.cleanup_orphaned_sync_sessions",
            "schedule": crontab(minute=0, hour="*/1"),  # every hour
        },
        "send-job-alert-digests": {
            "task": "app.tasks.job_alerts.send_job_alert_digests",
            "schedule": crontab(minute=10, hour="*/1"),  # hourly at :10
        },
        "maintain-known-people-cache": {
            "task": "app.tasks.known_people.maintain_known_people_cache",
            "schedule": crontab(minute=45, hour="*/8"),  # every 8 hours
        },
        "process-pending-sends": {
            "task": "app.tasks.auto_prospect.process_pending_sends",
            "schedule": crontab(minute="*/5"),  # every 5 minutes
        },
        "reconcile-outreach-sends": {
            "task": "app.tasks.outreach_reconcile.reconcile_outreach_sends",
            "schedule": crontab(minute="*/30"),  # sends + replies, every 30 minutes
        },
        "send-cadence-digests": {
            "task": "app.tasks.cadence_digest.send_cadence_digests",
            "schedule": crontab(minute=0, hour=9, day_of_week=1),  # Monday 09:00 UTC
        },
        "verify-curated-boards": {
            "task": "app.tasks.jobs.verify_curated_boards",
            "schedule": crontab(minute=0, hour=6, day_of_week=1),  # Monday 06:00 UTC
        },
    },
)

# Celery autodiscover looks for an app.tasks.tasks module by default. Our task
# modules live directly under app.tasks, so import them explicitly to make the
# Railway `celery -A app.tasks worker` command register every beat target.
celery_app.autodiscover_tasks(["app.tasks"])

for module_name in (
    "app.tasks.auto_prospect",
    "app.tasks.cadence_digest",
    "app.tasks.job_alerts",
    "app.tasks.jobs",
    "app.tasks.known_people",
    "app.tasks.linkedin_graph",
    "app.tasks.outreach_reconcile",
    "app.tasks.reverify",
):
    import_module(module_name)
