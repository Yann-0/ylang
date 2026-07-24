"""Tests for console database restore."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from ylang.console import register_console_routes
from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.core.stores import open_stores
from ylang.gateway.routes import register_gateway_routes
from ylang.mcp.auth import BearerTokenMiddleware
from ylang.mcp.deps import YlangDeps
from ylang.settings import ProviderKeys, Settings

_AUTH_HEADERS = {"Authorization": "Bearer secret-token"}


@pytest.fixture
def restore_client(tmp_path: Path, ylang_deps: YlangDeps) -> TestClient:
    db_path = tmp_path / "ylang.db"
    settings = Settings(
        transport="http",
        auth_token="secret-token",
        storage_path=db_path,
        provider_keys=ProviderKeys(openai="test-key"),
    )
    router = ModelRouter(
        activity_model_lists={"code": ["openai/gpt-4o"], "other": ["openai/gpt-4o"]},
        provider_keys=ProviderKeys(openai="test-key"),
    )
    engine = Engine(ylang_deps.store, surface="gateway", router=router)
    server = FastMCP("ylang-restore-test", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    register_console_routes(server, ylang_deps, settings, gateway_engine=engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), "secret-token")
    return TestClient(app)


def test_console_ops_restore(restore_client: TestClient, tmp_path: Path) -> None:
    live_path = tmp_path / "ylang.db"
    stores = open_stores(live_path)
    stores.close()
    backup_path = tmp_path / "backup.db"
    with sqlite3.connect(live_path) as src, sqlite3.connect(backup_path) as dst:
        src.backup(dst)
    response = restore_client.post(
        "/console/ops/restore",
        headers=_AUTH_HEADERS,
        data={"confirm": "RESTORE"},
        files={
            "file": (
                "backup.db",
                backup_path.read_bytes(),
                "application/octet-stream",
            )
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert live_path.is_file()
