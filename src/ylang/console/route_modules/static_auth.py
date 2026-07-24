"""Console routes: static auth."""

from __future__ import annotations


from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
)

from ylang.console.context import (
    STATIC_DIR,
    ConsoleContext,
)
from ylang.console.pages_full import (
    render_login_page,
)
from ylang.console.route_helpers import (
    _token_ok,
)
from ylang.mcp.auth import SESSION_COOKIE, session_cookie_kwargs


def register_static_auth_routes(ctx: ConsoleContext) -> None:
    """Register static_auth console routes."""
    @ctx.server.custom_route("/console/static/{path:path}", methods=["GET"])
    async def console_static(request: Request) -> Response:
        rel = request.path_params.get("path", "")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            return Response("Not found", status_code=404)
        if not target.is_file():
            return Response("Not found", status_code=404)
        response = FileResponse(target)
        # Fingerprinted/vendor assets change rarely; allow short browser cache.
        suffix = target.suffix.lower()
        if suffix in {".js", ".css", ".map", ".woff2", ".woff"}:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


    @ctx.server.custom_route("/console/login", methods=["GET", "POST"])
    async def console_login(request: Request) -> Response:
        next_path = request.query_params.get("next", "/console")
        if request.method == "GET":
            return HTMLResponse(render_login_page(next_path=next_path))
        form = await request.form()
        token = str(form.get("token", "")).strip()
        next_path = str(form.get("next", "/console")).strip() or "/console"
        if not _token_ok(token, ctx.settings):
            return HTMLResponse(
                render_login_page(next_path=next_path, error="Invalid token."),
                status_code=401,
            )
        response = RedirectResponse(next_path, status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=60 * 60 * 24 * 30,
            **session_cookie_kwargs(),
        )
        return response


    @ctx.server.custom_route("/console/logout", methods=["POST", "GET"])
    async def console_logout(_request: Request) -> Response:
        response = RedirectResponse("/console/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, **session_cookie_kwargs())
        return response

