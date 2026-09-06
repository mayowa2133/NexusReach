"""API-side client for the renderer's dedicated broker."""

from functools import lru_cache

from celery import Celery

from app.config import settings


@lru_cache(maxsize=1)
def _client() -> Celery:
    if not settings.renderer_redis_url:
        raise RuntimeError("Dedicated renderer broker is not configured")
    return Celery(
        "nexusreach-render-client",
        broker=settings.renderer_redis_url,
        backend=settings.renderer_redis_url,
    )


def submit_pdf(content: str):
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Render input is oversized.")
    return _client().send_task("renderer.render_pdf", args=[content], queue="render")
