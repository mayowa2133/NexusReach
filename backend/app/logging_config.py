"""Logging and Sentry configuration.

Call ``setup()`` once at import-time from ``app.main`` before the FastAPI app
is used.  In production, logs are emitted as single-line JSON for structured
aggregation (Railway, Datadog, etc.).  In development, the default human-
readable format is kept.

Sentry is initialised when ``NEXUSREACH_SENTRY_DSN`` is set.
"""

from __future__ import annotations

import logging
import sys

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from app.config import settings


def _configure_json_logging() -> None:
    """Replace the root logger formatter with structured JSON output."""
    from pythonjsonlogger.json import JsonFormatter

    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _configure_text_logging() -> None:
    """Readable text format for local development."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _init_sentry() -> None:
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            HttpxIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
            LoggingIntegration(
                level=logging.WARNING,
                event_level=logging.ERROR,
            ),
        ],
    )
    logging.getLogger(__name__).info(
        "Sentry initialized",
        extra={
            "environment": settings.environment,
            "traces_sample_rate": settings.sentry_traces_sample_rate,
        },
    )


_setup_done = False


def setup() -> None:
    """One-shot setup — safe to call multiple times."""
    global _setup_done  # noqa: PLW0603
    if _setup_done:
        return
    _setup_done = True

    if settings.log_format == "json":
        _configure_json_logging()
    else:
        _configure_text_logging()

    _init_sentry()
