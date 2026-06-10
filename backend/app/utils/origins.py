"""Shared allowed-origin computation for CORS and OAuth redirect validation.

Centralizing this (audit M6) keeps the OAuth redirect allowlist in lockstep
with the CORS policy. In production only the configured frontend + companion
extension origins are trusted; the localhost dev defaults in ``cors_origins``
are intentionally NOT trusted.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.config import settings


def origin_of(url: str | None) -> str | None:
    """Return the ``scheme://host[:port]`` origin of an http(s) URL, else None."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def allowed_frontend_origins() -> set[str]:
    """Origins the app is served from — production-aware (audit M6).

    Production trusts only ``frontend_url`` + configured companion extension
    origins. Non-production additionally trusts the ``cors_origins`` dev
    defaults (localhost). Used by OAuth ``redirect_uri`` validation so a
    production flow can never accept a localhost redirect.
    """
    origins: set[str] = set()

    fe = origin_of(settings.frontend_url)
    if fe:
        origins.add(fe)

    for raw in settings.companion_extension_origins or []:
        parsed = origin_of(raw)
        if parsed:
            origins.add(parsed)

    if settings.environment != "production":
        for raw in settings.cors_origins or []:
            parsed = origin_of(raw)
            if parsed:
                origins.add(parsed)

    return origins
