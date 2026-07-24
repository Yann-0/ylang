"""HTTP-only bearer token and session cookie gate."""

from __future__ import annotations

import secrets
from urllib.parse import quote

from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

SESSION_COOKIE = "ylang_token"
_SESSION_COOKIE = SESSION_COOKIE
_CONSOLE_PUBLIC_PATHS = frozenset({"/console/login"})
_CONSOLE_PUBLIC_PREFIXES = ("/console/static/",)


def session_cookie_kwargs(*, secure: bool = False) -> dict[str, str | bool]:
    """Return Starlette ``set_cookie`` kwargs safe for HTTP LAN console access.

    Uses ``path=/`` so the session is sent on all console routes regardless of
    hostname (``stelsrv-d001``, not only ``127.0.0.1``). ``secure`` stays off
    for plain HTTP deployments.
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": secure,
    }


def _authorization_header(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"authorization":
            return value.decode("latin-1")
    return None


def _cookie_token(scope: Scope, cookie_name: str) -> str | None:
    for name, value in scope.get("headers", ()):
        if name.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            stripped = part.strip()
            if stripped.startswith(f"{cookie_name}="):
                return stripped.split("=", 1)[1].strip()
    return None


def _is_console_public(path: str) -> bool:
    if path in _CONSOLE_PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _CONSOLE_PUBLIC_PREFIXES)


class BearerTokenMiddleware:
    """Reject HTTP requests unless Bearer token or session cookie matches."""

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        *,
        previous_token: str | None = None,
    ) -> None:
        """Wrap ``app`` and require auth on HTTP requests."""
        self.app = app
        self._valid_tokens = [token]
        if previous_token:
            self._valid_tokens.append(previous_token)
        self._bearer_values = [f"Bearer {item}" for item in self._valid_tokens]

    def _authorized(self, scope: Scope) -> bool:
        auth = _authorization_header(scope)
        if auth is not None and any(
            secrets.compare_digest(auth, expected) for expected in self._bearer_values
        ):
            return True
        cookie = _cookie_token(scope, _SESSION_COOKIE)
        if cookie is not None and any(
            secrets.compare_digest(cookie, token) for token in self._valid_tokens
        ):
            return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("lifespan", "websocket"):
            await self.app(scope, receive, send)
            return

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/health" or _is_console_public(path):
            await self.app(scope, receive, send)
            return

        if self._authorized(scope):
            await self.app(scope, receive, send)
            return

        if path.startswith("/console"):
            query = scope.get("query_string", b"").decode("latin-1")
            next_path = path
            if query:
                next_path = f"{path}?{query}"
            location = f"/console/login?next={quote(next_path, safe='/?=&')}"
            response = RedirectResponse(location, status_code=303)
            await response(scope, receive, send)
            return

        response = Response("Unauthorized", status_code=401)
        await response(scope, receive, send)
