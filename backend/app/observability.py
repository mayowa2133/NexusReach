"""Runtime observability wiring for backend services."""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode

import posthog
import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import settings

logger = logging.getLogger(__name__)
_initialized = False
_SENSITIVE_KEYS = {
    "authorization", "code", "state", "token", "access_token",
    "refresh_token", "session_token", "client_secret", "api_key",
}


def telemetry_enabled() -> bool:
    """Return whether this process may emit telemetry externally.

    Test runners often inherit a developer shell and load ``backend/.env``.
    Environment isolation, not merely an empty key, must therefore guarantee
    that unit and end-to-end fixtures can never reach a real telemetry project.
    """
    return settings.environment not in {"test", "e2e"}


def _scrub_mapping(value):
    if isinstance(value, dict):
        return {
            key: ("[Filtered]" if str(key).lower() in _SENSITIVE_KEYS else _scrub_mapping(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_mapping(item) for item in value]
    return value


def _before_send(event, _hint):
    event = _scrub_mapping(event)
    request = event.get("request") if isinstance(event, dict) else None
    if isinstance(request, dict):
        query = request.get("query_string")
        if isinstance(query, str):
            request["query_string"] = urlencode(
                [
                    (key, "[Filtered]" if key.lower() in _SENSITIVE_KEYS else val)
                    for key, val in parse_qsl(query, keep_blank_values=True)
                ]
            )
        url = str(request.get("url") or "")
        if "/api/email/oauth/connect" in url:
            request["data"] = "[Filtered OAuth callback body]"
    return event


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
    if not telemetry_enabled() or not settings.posthog_api_key:
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
    if not telemetry_enabled() or not settings.posthog_api_key:
        return
    try:
        posthog.set(distinct_id, properties or {})
    except Exception:  # pragma: no cover - telemetry must never break a request
        logger.warning("PostHog identify failed", exc_info=True)


def init_sentry(service_name: str) -> None:
    """Initialize Sentry once when a DSN is configured."""
    global _initialized
    if _initialized or not telemetry_enabled() or not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.app_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_before_send,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            CeleryIntegration(),
        ],
    )
    sentry_sdk.set_tag("service", service_name)
    _initialized = True
    logger.info("Sentry initialized for %s", service_name)
