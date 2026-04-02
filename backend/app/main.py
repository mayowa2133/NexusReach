import logging

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
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
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="NexusReach API",
    description="Smart personal networking assistant",
    version="0.2.0",
)

# --- Rate limiter ---
app.state.limiter = limiter

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [settings.frontend_url]
        if settings.environment == "production"
        else settings.cors_origins
    ),
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


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def log_auth_mode() -> None:
    if settings.auth_mode == "dev":
        logger.warning(
            "NEXUSREACH_AUTH_MODE=dev is enabled. Supabase auth is bypassed and all requests run as %s.",
            settings.dev_user_email,
        )
