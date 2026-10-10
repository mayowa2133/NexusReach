"""Reject excessive bearer work before FastAPI resolves auth dependencies."""

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.utils.client_ip import client_ip
from app.utils.resource_limits import consume, identity_key


class AuthAdmissionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        authorization = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
        try:
            if len(authorization) > 1:
                raise HTTPException(400, "Supply a single authorization header.")
            if authorization and authorization[0].lower().startswith(b"bearer "):
                if len(authorization[0]) > settings.max_bearer_header_bytes:
                    raise HTTPException(431, "Authorization header is too large.")
                # Referral/receipt capabilities do not consult JWT keys, but
                # still receive this cheap shared admission protection.
                source = identity_key(client_ip(Request(scope)) or "unknown")
                await consume([
                    ("bearer-global", settings.auth_global_requests_per_minute, 1),
                    (f"bearer-source:{source}", settings.auth_source_requests_per_minute, 1),
                ], window=60)
        except HTTPException as exc:
            response = JSONResponse(
                {"error": {"code": f"HTTP_{exc.status_code}", "message": exc.detail}},
                status_code=exc.status_code, headers=exc.headers,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
