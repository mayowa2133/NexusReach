"""Celery application and task registration."""

import asyncio
import os
import threading
from collections.abc import Coroutine
from importlib import import_module
from typing import Any, TypeVar

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.config import settings
from app.observability import init_sentry

_T = TypeVar("_T")
_async_runner: "_AsyncLoopRunner | None" = None
_async_runner_lock = threading.Lock()


class _AsyncLoopRunner:
    """Own one persistent asyncio loop for a Celery worker child process."""

    def __init__(self) -> None:
        self.pid = os.getpid()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run,
            name="celery-asyncio-loop",
            daemon=True,
        )
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()


def _get_async_runner() -> _AsyncLoopRunner:
    global _async_runner
    pid = os.getpid()
    with _async_runner_lock:
        if (
            _async_runner is None
            or _async_runner.pid != pid
            or not _async_runner.thread.is_alive()
        ):
            _async_runner = _AsyncLoopRunner()
        return _async_runner


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run async Celery work on a persistent per-process event loop.

    SQLAlchemy's asyncpg pool binds connections to the event loop that created
    them. Reusing one loop per prefork child prevents pooled connections from
    being reused by a different loop on the next Celery task.
    """
    return _get_async_runner().run(coro)


init_sentry("worker")


@worker_process_init.connect
def _configure_worker_db(**_kwargs: Any) -> None:
    """Give each forked worker child a fork/pooler-safe NullPool DB engine.

    Runs once per prefork child (after fork, before any task). See
    ``app.database.use_null_pool_engine`` for why the inherited pooled engine
    produces MissingGreenlet / ConnectionDoesNotExist errors on the Supabase
    pooler. Beat does not execute tasks, so only worker children need this.
    """
    from app.database import use_null_pool_engine

    use_null_pool_engine()


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
    worker_prefetch_multiplier=1,
    # Search/browser integrations retain native-library memory between tasks.
    # Recycle prefork children before that growth reaches Railway's 1 GB service
    # limit, and force a recycle after any task leaves a child above 300 MB RSS
    # (lowered from 400 MB when worker concurrency went 1 -> 2: two children
    # must fit under the same 1 GB cap).
    worker_max_tasks_per_child=5,
    worker_max_memory_per_child=300_000,
    # The per-job people pre-warm fan-out (up to PREWARM_MAX_JOBS_PER_BATCH
    # tasks per discovery, minutes each) gets its own queue so time-sensitive
    # work — scheduled email sends, feed refreshes, cold-start discovery —
    # never sits behind the backlog. The single Railway worker consumes both
    # queues (railway.worker.toml -Q celery,prewarm); to scale further, add a
    # second worker service consuming only -Q prewarm.
    task_routes={
        "app.tasks.auto_prospect.prewarm_job_people": {"queue": "prewarm"},
        "app.tasks.auto_prospect.prewarm_job_people_batch": {"queue": "prewarm"},
        "app.tasks.auto_prospect.refresh_job_research_snapshot": {"queue": "prewarm"},
        "app.tasks.render.render_pdf": {"queue": "render"},
        "app.tasks.render.render_redline_pdf": {"queue": "render"},
    },
    beat_schedule={
        "refresh-job-feeds": {
            "task": "app.tasks.jobs.refresh_all_job_feeds",
            # Hourly (was */15). Each refresh dedups every fetched job against the
            # DB, so its read volume is the largest driver of Supabase egress;
            # hourly keeps the feed fresh enough while staying under the free-tier
            # egress cap. See supabase-egress-overage memory.
            "schedule": crontab(minute=0),  # hourly
        },
        "discover-ats-boards": {
            "task": "app.tasks.jobs.discover_ats_boards",
            # Every 6h (was hourly). The full board crawl dedups ~24k jobs per run
            # — the single heaviest egress source — and the boards themselves
            # change slowly, so 6h loses little freshness for a large egress cut.
            "schedule": crontab(minute=7, hour="*/6"),  # every 6 hours, offset from feed refresh
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
        "retag-occupation-tags": {
            "task": "app.tasks.jobs.retag_occupation_tags",
            "schedule": crontab(minute=20, hour=4),  # daily 04:20 UTC (self-heal tags)
        },
        "monitor-source-health": {
            "task": "app.tasks.jobs.monitor_source_health",
            "schedule": crontab(minute=50, hour="*/1"),  # hourly at :50 (sustained-outage alerts)
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
    "app.tasks.render",
    "app.tasks.referrals",
    "app.tasks.waitlist_resume",
):
    import_module(module_name)
