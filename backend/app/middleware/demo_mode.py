"""Fail-closed side-effect policy for the synthetic Gideon demo."""

from __future__ import annotations

import re

from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings


_BLOCKED: tuple[tuple[frozenset[str], re.Pattern[str], str], ...] = (
    (frozenset({"GET"}), re.compile(r"^/api/companies/logo$"), "external company-logo retrieval"),
    (frozenset({"POST"}), re.compile(r"^/api/jobs(?:/|$)"), "job discovery and generated job artifacts"),
    (frozenset({"POST"}), re.compile(r"^/api/people(?:/|$)"), "people discovery and LinkedIn capture"),
    (frozenset({"POST"}), re.compile(r"^/api/messages(?:/|$)"), "LLM drafting and message-copy actions"),
    (frozenset({"GET", "POST"}), re.compile(r"^/api/email/(?:gmail/auth-url|outlook/auth-url|oauth/connect|find/|verify/|lookup|stage-draft|stage-drafts|send|gmail/disconnect|outlook/disconnect)"), "email lookup, OAuth, staging, and sending"),
    (frozenset({"POST", "DELETE"}), re.compile(r"^/api/linkedin-graph(?:/|$)"), "LinkedIn graph import and sync"),
    (frozenset({"POST"}), re.compile(r"^/api/profile/(?:import-linkedin|resume|resume-json)$"), "personal-data import"),
    (frozenset({"POST"}), re.compile(r"^/api/account/delete$"), "account deletion"),
    (frozenset({"POST"}), re.compile(r"^/api/waitlist$"), "waitlist submission"),
    (frozenset({"POST", "DELETE"}), re.compile(r"^/api/companion/token$"), "companion authorization"),
    (frozenset({"PUT"}), re.compile(r"^/api/settings/(?:auto-prospect|cadence)$"), "background automation settings"),
    (frozenset({"PUT", "POST"}), re.compile(r"^/api/settings/job-alerts(?:/|$)"), "email job alerts"),
    (frozenset({"POST"}), re.compile(r"^/api/jobs/[^/]+/interview-prep$"), "LLM interview preparation"),
)


def blocked_demo_action(method: str, path: str) -> str | None:
    normalized_method = method.upper()
    for methods, pattern, action in _BLOCKED:
        if normalized_method in methods and pattern.search(path):
            return action
    return None


class DemoModeSafetyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if settings.demo_mode:
            action = blocked_demo_action(request.method, request.url.path)
            if action:
                return ORJSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "DEMO_ACTION_DISABLED",
                            "message": f"Demo mode disables {action}.",
                            "details": None,
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )
        return await call_next(request)
