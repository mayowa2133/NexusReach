"""Minimal production API for the public Solomon prelaunch.

The full product API deliberately requires the isolated document renderer.
Railway does not provide every containment primitive that renderer attestation
requires, while the prelaunch only needs the waitlist and referral loop. This
entry point keeps those checks intact and exposes only the public prelaunch
surface until the full application is ready to ship.
"""

import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.middleware.error_handler import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.middleware.rate_limit import limiter
from app.middleware.request_size import RequestSizeLimitMiddleware
from app.observability import init_sentry
from app.routers import deletions, referrals, waitlist
from app.utils.client_ip import client_ip

logger = logging.getLogger(__name__)
init_sentry("waitlist")

app = FastAPI(
    title="Solomon Waitlist API",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)
app.state.limiter = limiter

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def sensitive_flow_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/referrals", "/api/deletions")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Pragma"] = "no-cache"
    return response


app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(waitlist.router, prefix="/api")
app.include_router(referrals.router, prefix="/api")
app.include_router(deletions.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/ready")
async def readiness(
    request: Request,
    x_readiness_token: str | None = Header(default=None),
) -> JSONResponse:
    if (
        not settings.readiness_token
        or not x_readiness_token
        or not hmac.compare_digest(x_readiness_token, settings.readiness_token)
    ):
        raise HTTPException(status_code=404, detail="Not found")

    checks: dict[str, str] = {}
    try:
        from sqlalchemy import text

        from app.database import async_session

        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        logger.warning("Readiness check: postgres unavailable", exc_info=True)
        checks["postgres"] = "error"

    try:
        from app.clients import search_cache_client

        checks["redis"] = "ok" if await search_cache_client.ping() else "error"
    except Exception:
        logger.warning("Readiness check: redis unavailable", exc_info=True)
        checks["redis"] = "error"

    status_code = 200 if all(value == "ok" for value in checks.values()) else 503
    return JSONResponse(
        {
            "status": "ok" if status_code == 200 else "error",
            "checks": checks,
            "client_ip": client_ip(request),
        },
        status_code=status_code,
    )
