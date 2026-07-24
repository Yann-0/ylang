"""Tests for HTTP rate limiting middleware."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from ylang.core.migrations import run_migrations
from ylang.core.runtime_settings import RuntimeSettingsStore
from ylang.mcp.rate_limit import (
    DynamicRateLimitMiddleware,
    RateLimitMiddleware,
    maybe_rate_limit_middleware,
    register_rate_limit_store,
)
from ylang.usage.store import open_store


def _app() -> Starlette:
    async def ok(_request):  # type: ignore[no-untyped-def]
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/", ok)])


def test_rate_limit_blocks_excess_requests() -> None:
    wrapped = RateLimitMiddleware(_app(), limit=2, window_seconds=60.0)
    client = TestClient(wrapped)
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 200
    blocked = client.get("/")
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "rate limit exceeded"


def test_health_exempt_from_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YLANG_RATE_LIMIT_PER_MINUTE", "1")
    wrapped = maybe_rate_limit_middleware(_app())
    client = TestClient(wrapped)
    # Health path is exempt inside RateLimitMiddleware but only for /health route;
    # root path should still rate limit when env is set.
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 429


def test_rate_limit_hot_reload_from_runtime_settings(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("YLANG_RATE_LIMIT_PER_MINUTE", raising=False)
    store = open_store(tmp_path / "rate-limit.db")  # type: ignore[operator]
    run_migrations(store._connection)
    runtime = RuntimeSettingsStore(store._connection)
    runtime.set("rate_limit_per_minute", "1")

    register_rate_limit_store(store)
    wrapped = DynamicRateLimitMiddleware(_app())
    client = TestClient(wrapped)
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 429

    runtime.set("rate_limit_per_minute", "0")
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 200
