def test_beat_schedule_tasks_are_registered_by_worker_app():
    from app.tasks import celery_app

    celery_app.loader.import_default_modules()
    celery_app.finalize(auto=True)

    missing = [
        entry["task"]
        for entry in celery_app.conf.beat_schedule.values()
        if entry["task"] not in celery_app.tasks
    ]
    assert missing == []


def test_job_refresh_cadence_is_every_fifteen_minutes():
    from app.tasks import celery_app

    schedule = celery_app.conf.beat_schedule["refresh-job-feeds"]["schedule"]

    assert schedule._orig_minute == "*/15"
