"""HTTP-level protections (2.3): response security headers and a body size cap.

Both are plain ASGI middleware, so they apply to every route, including
errors raised before a route runs.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.exceptions import HTTPException

# Interactive docs load Swagger UI / ReDoc scripts and styles from a CDN, so
# the strict API policy below would blank them. They get no CSP (they are off
# in production unless asked for).
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
)


class SecurityHeadersMiddleware:
    """Add security headers to every HTTP response.

    API responses also get ``Cache-Control: no-store`` (they carry borrower
    and credit data that a shared browser or proxy cache must not keep) and a
    deny-everything Content-Security-Policy. ``Strict-Transport-Security`` is
    sent only when the request arrived over HTTPS (directly or via a proxy
    that says so), since browsers ignore it on plain HTTP.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        is_docs = path.startswith(_DOCS_PATHS)
        headers_in = {key.lower(): value for key, value in scope.get("headers", [])}
        https = scope.get("scheme") == "https" or headers_in.get(b"x-forwarded-proto") == b"https"

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                extra = list(SECURITY_HEADERS)
                if not is_docs:
                    extra.append((b"content-security-policy", API_CSP.encode()))
                    extra.append((b"cache-control", b"no-store"))
                if https:
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                headers.extend((key, value) for key, value in extra if key not in present)
                # Do not advertise the server software.
                headers = [(k, v) for k, v in headers if k.lower() != b"server"]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _BodyTooLarge(HTTPException):
    """Raised mid-body. An HTTPException, so FastAPI's body reader re-raises it
    as itself (a 413) instead of turning it into a generic 400."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=413, detail=detail)


class BodySizeLimitMiddleware:
    """Refuse request bodies larger than ``max_bytes`` with 413.

    A declared ``Content-Length`` over the limit is refused before the body is
    read; a chunked body is counted as it arrives and refused once it passes
    the limit. A malformed ``Content-Length`` is a 400.
    """

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = None
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    await _reply(send, 400, "Malformed Content-Length header.")
                    return
                if declared < 0:
                    await _reply(send, 400, "Malformed Content-Length header.")
                    return
        if declared is not None and declared > self.max_bytes:
            await _reply(send, 413, self._message())
            return

        received = 0
        started = False

        async def counting_receive() -> dict:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge(self._message())
            return message

        async def tracking_send(message: dict) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await _reply(send, 413, self._message())

    def _message(self) -> str:
        return f"Request body is larger than {self.max_bytes // 1024} KiB."


async def _reply(send: Any, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
