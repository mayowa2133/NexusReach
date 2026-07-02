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


def test_job_refresh_cadence_is_hourly_to_bound_egress():
    # Lowered from */15 to hourly to keep Supabase egress under the free-tier
    # cap: each refresh dedups every fetched job against the DB, so its read
    # volume is the largest egress driver. See supabase-egress-overage memory.
    from app.tasks import celery_app

    schedule = celery_app.conf.beat_schedule["refresh-job-feeds"]["schedule"]

    assert schedule._orig_minute == 0
    assert schedule._orig_hour == "*"


def test_ats_board_crawl_cadence_is_every_six_hours_to_bound_egress():
    from app.tasks import celery_app

    schedule = celery_app.conf.beat_schedule["discover-ats-boards"]["schedule"]

    assert schedule._orig_hour == "*/6"


def test_worker_runtime_defaults_limit_prefetch_and_child_reuse():
    from app.config import Settings
    from app.tasks import celery_app

    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.worker_max_tasks_per_child == 5
    assert celery_app.conf.worker_max_memory_per_child == 300_000
    # The people pre-warm fan-out must stay on its own queue so beat tasks
    # (email sends, feed refreshes) never queue behind its backlog.
    routes = celery_app.conf.task_routes
    assert routes["app.tasks.auto_prospect.prewarm_job_people"] == {"queue": "prewarm"}
    assert routes["app.tasks.auto_prospect.refresh_job_research_snapshot"] == {"queue": "prewarm"}
    assert Settings.model_fields["reverify_batch_size"].default == 5


def test_linkedin_cleanup_uses_shared_async_runner(monkeypatch):
    from app.tasks import linkedin_graph

    expected = {"expired": 2}

    def fake_run_async(coro):
        coro.close()
        return expected

    monkeypatch.setattr(linkedin_graph, "run_async", fake_run_async)

    assert linkedin_graph.cleanup_orphaned_sync_sessions_task.run() == expected
