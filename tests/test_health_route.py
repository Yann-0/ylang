"""Health endpoint tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ylang.gateway.routes import register_health_route
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.mcp.server import create_server
from ylang.mcp.deps import YlangDeps


@pytest.mark.asyncio
async def test_health_unauthenticated(ylang_deps: YlangDeps) -> None:
    server = create_server(ylang_deps)
    register_health_route(server)
    app = BearerTokenMiddleware(server.streamable_http_app(), "secret-token")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "ylang"
