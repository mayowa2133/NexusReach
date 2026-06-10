"""Runtime observability wiring for backend services."""

from __future__ import annotations

import logging

import posthog
import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import settings

logger = logging.getLogger(__name__)
_initialized = False


def capture_event(
    distinct_id: str,
    event: str,
    *,
    properties: dict | None = None,
) -> None:
    """Send a PostHog event only when analytics is configured.

    ``posthog.capture`` raises ``AssertionError`` when ``api_key`` is unset,
    which would turn every analytics call into a 500. Guarding at one boundary
    keeps capture calls safe and uniform across routers, and never lets a
    telemetry failure surface to the user.
    """
    if not settings.posthog_api_key:
        return
    try:
        posthog.capture(distinct_id, event, properties=properties or {})
    except Exception:  # pragma: no cover - telemetry must never break a request
        logger.warning("PostHog capture failed for event %s", event, exc_info=True)


def identify_user(distinct_id: str, properties: dict | None = None) -> None:
    """Set PostHog person properties only when analytics is configured.

    Mirrors ``capture_event``: guarded and exception-safe so identifying a user
    can never break the request that triggered it.
    """
    if not settings.posthog_api_key:
        return
    try:
        posthog.set(distinct_id, properties or {})
    except Exception:  # pragma: no cover - telemetry must never break a request
        logger.warning("PostHog identify failed", exc_info=True)


def init_sentry(service_name: str) -> None:
    """Initialize Sentry once when a DSN is configured."""
    global _initialized
    if _initialized or not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.app_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            CeleryIntegration(),
        ],
    )
    sentry_sdk.set_tag("service", service_name)
    _initialized = True
    logger.info("Sentry initialized for %s", service_name)
