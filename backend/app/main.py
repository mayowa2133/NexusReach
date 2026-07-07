import logging

import posthog
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.observability import init_sentry
from app.middleware.error_handler import (
    http_exception_handler,
    validation_exception_handler,
    unhandled_exception_handler,
)
from app.middleware.rate_limit import limiter
from app.routers import (
    auth,
    profile,
    people,
    messages,
    email,
    jobs,
    companies,
    outreach,
    notifications,
    insights,
    settings as settings_router,
    usage,
    linkedin_graph,
    job_alerts,
    known_people,
    stories,
    cadence,
    interview_prep,
    triage,
    occupations,
    account,
    waitlist,
)

logger = logging.getLogger(__name__)
init_sentry("api")

app = FastAPI(
    title="NexusReach API",
    description="Smart personal networking assistant",
    version="0.2.0",
    # orjson renders large JSON payloads (e.g. the jobs feed) several times
    # faster than the stdlib encoder.
    default_response_class=ORJSONResponse,
)


def _cors_origins() -> list[str]:
    if settings.environment == "production":
        return [settings.frontend_url, *settings.companion_extension_origins]
    return [*settings.cors_origins, *settings.companion_extension_origins]


def _cors_origin_regex() -> str | None:
    if settings.companion_extension_origin_regex:
        return settings.companion_extension_origin_regex
    if settings.environment != "production":
        return r"^chrome-extension://[a-z]{32}$"
    return None

# --- Rate limiter ---
app.state.limiter = limiter

# --- Middleware ---
# GZip is added before CORS so CORS ends up outermost (last-added wraps first)
# and error responses keep their CORS headers. Text JSON compresses ~10x.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Exception handlers ---
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# --- Routers ---
app.include_router(auth.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(people.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(email.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(companies.router, prefix="/api")
app.include_router(outreach.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(usage.router, prefix="/api")
app.include_router(linkedin_graph.router, prefix="/api")
app.include_router(job_alerts.router, prefix="/api")
app.include_router(known_people.router, prefix="/api")
app.include_router(stories.router, prefix="/api")
app.include_router(cadence.router, prefix="/api")
app.include_router(interview_prep.router, prefix="/api")
app.include_router(triage.router, prefix="/api")
app.include_router(occupations.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(waitlist.router, prefix="/api")


@app.get("/api/health")
async def health():
    """Health check that verifies core dependencies.

    Returns only a coarse ok/error per check (audit M4). This endpoint is
    unauthenticated, so raw exception detail (which can leak DB host/driver
    internals) is logged server-side rather than returned to the caller.
    """
    checks: dict[str, str] = {}

    # Postgres
    try:
        from app.database import async_session as _session_factory
        from sqlalchemy import text

        async with _session_factory() as db:
            await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        logger.warning("Health check: postgres unavailable", exc_info=True)
        checks["postgres"] = "error"

    # Redis
    try:
        from app.clients import search_cache_client

        pong = await search_cache_client.ping()
        checks["redis"] = "ok" if pong else "error"
    except Exception:
        logger.warning("Health check: redis unavailable", exc_info=True)
        checks["redis"] = "error"

    healthy = all(v == "ok" for v in checks.values())
    status_code = 200 if healthy else 503
    from fastapi.responses import JSONResponse

    return JSONResponse(
        content={"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=status_code,
    )


@app.on_event("startup")
async def init_posthog() -> None:
    if settings.posthog_api_key:
        posthog.api_key = settings.posthog_api_key
        posthog.host = settings.posthog_host
        posthog.debug = settings.environment != "production"


@app.on_event("shutdown")
async def shutdown_posthog() -> None:
    if settings.posthog_api_key:
        posthog.flush()


@app.on_event("startup")
async def log_auth_mode() -> None:
    if settings.auth_mode == "dev":
        if settings.dev_auth_bypass_enabled:
            logger.warning(
                "NEXUSREACH_AUTH_MODE=dev and NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=true are enabled. "
                "Supabase auth is bypassed and all requests run as %s.",
                settings.dev_user_email,
            )
        else:
            logger.error(
                "NEXUSREACH_AUTH_MODE=dev is set without NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=true. "
                "Authenticated requests will fail closed."
            )
