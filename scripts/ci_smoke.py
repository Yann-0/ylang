"""Exercise the installed wheel with synthetic state and no provider calls."""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.resources
import json
from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

import ylang
from ylang.core.engine import Engine
from ylang.core.model_aliases import load_cursor_slug_aliases
from ylang.core.stores import open_stores
from ylang.gateway.routes import register_gateway_routes
from ylang.improver import Improver
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.mcp.deps import YlangDeps
from ylang.mcp.server import create_server
from ylang.settings import Settings


def main() -> None:
    """Verify artifact identity, MCP persistence, auth and static resources."""
    origin = Path(ylang.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve())
    assert ylang.__version__ == importlib.metadata.version("ylang") == sys.argv[1]
    assert load_cursor_slug_aliases() == json.loads(Path(sys.argv[2]).read_text())
    stores = open_stores(Settings.load().resolved_storage_path())
    try:
        engine = Engine(stores.store, surface="ci-smoke")
        mcp = create_server(YlangDeps(
            improver=Improver(engine), library=stores.library, store=stores.store,
            memory=stores.memory, surface="mcp",
        ))

        async def check_tools() -> int:
            """Round-trip synthetic templates and scoped facts through MCP."""
            names = {tool.name for tool in await mcp.list_tools()}
            assert {"improve_prompt", "save_template", "recall_facts"} <= names
            await mcp.call_tool("save_template", {
                "template_id": "ci-smoke", "name": "CI smoke",
                "body": "Synthetic package fixture.", "params": [],
            })
            _, template = await mcp.call_tool("recall_template", {"template_id": "ci-smoke"})
            assert "Synthetic package fixture." in json.dumps(template)
            await mcp.call_tool("remember", {
                "fact": "Synthetic memory fixture.", "scope": "private", "workspace": "ci-smoke",
            })
            _, facts = await mcp.call_tool("recall_facts", {
                "scope": "private", "workspace": "ci-smoke", "limit": 5,
            })
            assert "Synthetic memory fixture." in json.dumps(facts)
            return len(names)

        tools = asyncio.run(check_tools())
        gateway = FastMCP("ci-smoke", streamable_http_path="/mcp")
        register_gateway_routes(gateway, engine)
        app = BearerTokenMiddleware(gateway.streamable_http_app(), "synthetic-ci-token")
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/v1/models").status_code == 401
            assert client.get("/v1/models", headers={
                "Authorization": "Bearer synthetic-ci-token",
            }).status_code == 200
        assets = importlib.resources.files("ylang.console").joinpath("static")
        assert any(p.name == "chart.umd.min.js" for p in assets.iterdir())
        print(json.dumps({"status": "PASS", "version": ylang.__version__,
                          "installed_origin": str(origin), "mcp_tool_count": tools,
                          "provider_calls": 0, "quality_improvement_claim": False}))
    finally:
        stores.close()


if __name__ == "__main__":
    main()
