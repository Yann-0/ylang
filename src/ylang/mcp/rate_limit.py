"""Optional per-IP rate limiting for HTTP transport."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    if client is None:
        return "unknown"
    return str(client[0])


class RateLimitMiddleware:
    """Simple sliding-window request limiter per client IP."""

    def __init__(self, app: ASGIApp, *, limit: int, window_seconds: float) -> None:
        self.app = app
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/health":
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        ip = _client_ip(scope)
        bucket = self._hits[ip]
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            response: Response = JSONResponse(
                {"error": "rate limit exceeded"},
                status_code=429,
            )
            await response(scope, receive, send)
            return
        bucket.append(now)
        await self.app(scope, receive, send)


def maybe_rate_limit_middleware(app: ASGIApp) -> ASGIApp:
    """Wrap ``app`` when ``YLANG_RATE_LIMIT_PER_MINUTE`` is set."""
    raw = os.environ.get("YLANG_RATE_LIMIT_PER_MINUTE")
    if not raw or not raw.strip():
        return app
    limit = int(raw.strip())
    if limit <= 0:
        return app
    return RateLimitMiddleware(app, limit=limit, window_seconds=60.0)
