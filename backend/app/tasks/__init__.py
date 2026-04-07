"""Celery application and task registration."""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

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
            "schedule": crontab(minute="0,30"),  # every 30 minutes
        },
        "discover-ats-boards": {
            "task": "app.tasks.jobs.discover_ats_boards",
            "schedule": crontab(minute="15,45"),  # every 30 minutes (offset)
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
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])
