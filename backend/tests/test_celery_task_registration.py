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


def test_linkedin_cleanup_uses_shared_async_runner(monkeypatch):
    from app.tasks import linkedin_graph

    expected = {"expired": 2}

    def fake_run_async(coro):
        coro.close()
        return expected

    monkeypatch.setattr(linkedin_graph, "run_async", fake_run_async)

    assert linkedin_graph.cleanup_orphaned_sync_sessions_task.run() == expected
