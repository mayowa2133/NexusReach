"""Early request-body limits, including chunked requests without Content-Length."""

from __future__ import annotations

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings


def _limit_for_path(path: str) -> int:
    if path == "/api/profile/resume-json":
        return settings.max_resume_json_request_bytes
    if path == "/api/profile/resume":
        return settings.max_resume_upload_bytes
    if path == "/api/linkedin-graph/import-file":
        return settings.max_linkedin_upload_bytes
    return settings.max_request_body_bytes


class RequestSizeLimitMiddleware:
    """Reject oversized HTTP bodies before route parsing or Pydantic validation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _limit_for_path(scope.get("path", ""))
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > limit:
                    await self._send_too_large(send, limit)
                    return
            except ValueError:
                await self._send_too_large(send, limit)
                return

        seen = 0

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise HTTPException(status_code=413, detail="Request body is too large.")
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _send_too_large(send: Send, limit: int) -> None:
        body = b'{"error":{"code":"HTTP_413","message":"Request body is too large.","details":null}}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"x-request-body-limit", str(limit).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
