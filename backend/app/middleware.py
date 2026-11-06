"""HTTP hardening applied to every API response (pure ASGI, so streaming is unaffected).

- Security headers: no MIME sniffing, no framing, no referrer leakage, no caching of
  per-user operational data, and HSTS when cookies are HTTPS-only.
- Request size limit: bodies declared larger than the upload limit (+1 MiB for form
  overhead) are refused with 413 before any of the body is read. The hosting proxy should
  also cap body size, because chunked requests do not declare a length up front.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import get_settings

_BASE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        settings = get_settings()
        self.extra = [*_BASE_HEADERS, *([_HSTS] if settings.cookie_secure else [])]
        self.limit = settings.max_upload_bytes + 1024 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = next((v for k, v in scope["headers"] if k == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            await self._too_large(send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in self.extra if k not in present]
                if b"cache-control" not in present and scope["path"].startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)

    async def _too_large(self, send: Send) -> None:
        body = json.dumps(
            {"detail": f"Request body too large (limit {self.limit // (1024 * 1024)} MB)."}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    *self.extra,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
