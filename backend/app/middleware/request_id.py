"""Request-ID middleware.

Assigns a unique ID to every request and attaches it to:
- the response ``X-Request-ID`` header
- the Sentry scope (if Sentry is initialised)
- a ``contextvars``-based context so any log statement during the
  request can include it via the ``request_id`` extra field.
"""

from __future__ import annotations

import contextvars
import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Context variable — available to any code running inside a request
# ---------------------------------------------------------------------------
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def get_request_id() -> str:
    """Return the current request ID (empty string outside a request)."""
    return _request_id_var.get()


# ---------------------------------------------------------------------------
# Logging filter — automatically injects request_id into every log record
# ---------------------------------------------------------------------------


class RequestIdFilter(logging.Filter):
    """Inject ``request_id`` into every LogRecord so JSON formatters pick it up."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Prefer a client-supplied header (e.g. from a load balancer)
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        _request_id_var.set(request_id)

        # Attach to Sentry scope if available
        try:
            import sentry_sdk

            scope = sentry_sdk.get_current_scope()
            scope.set_tag("request_id", request_id)
        except Exception:  # pragma: no cover
            pass

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
