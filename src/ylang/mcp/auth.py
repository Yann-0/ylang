"""HTTP-only bearer token gate for the streamable MCP transport."""

from __future__ import annotations

import secrets

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


def _authorization_header(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"authorization":
            return value.decode("latin-1")
    return None


class BearerTokenMiddleware:
    """Reject HTTP requests whose Authorization header is not ``Bearer <token>``."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        """Wrap ``app`` and require ``Authorization: Bearer <token>`` on HTTP requests."""
        self.app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("lifespan", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        auth = _authorization_header(scope)
        if auth is None or not secrets.compare_digest(auth, self._expected):
            response = Response("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
