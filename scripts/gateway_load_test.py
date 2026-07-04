#!/usr/bin/env python3
"""Lightweight concurrent load test for the OpenAI gateway routes.

Runs against a Starlette TestClient with a mocked Engine by default.
Pass ``--live URL TOKEN`` to probe a running HTTP service (no LLM calls).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Allow running from repo root without install.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))


def _mock_client(concurrency: int, requests: int) -> dict[str, float]:
    """Run concurrent /v1/models requests against an in-process TestClient."""
    from unittest.mock import patch

    from mcp.server.fastmcp import FastMCP
    from starlette.testclient import TestClient

    from ylang.core.engine import Engine
    from ylang.core.model_router import ModelRouter
    from ylang.core.types import CompletionResult
    from ylang.gateway.routes import register_gateway_routes
    from ylang.mcp.auth import BearerTokenMiddleware
    from ylang.settings import ProviderKeys
    from ylang.usage.store import open_store

    db_path = Path("/tmp/ylang-gateway-load-test.db")
    store = open_store(db_path)
    router = ModelRouter(
        activity_model_lists={"other": ["openai/gpt-4o"]},
        provider_keys=ProviderKeys(openai="test"),
        fallback_model="ollama/qwen2.5",
    )
    engine = Engine(store, surface="gateway-load-test", router=router)
    server = FastMCP("ylang-load-test", streamable_http_path="/mcp")
    register_gateway_routes(server, engine)
    app = BearerTokenMiddleware(server.streamable_http_app(), "load-test-token")
    client = TestClient(app)

    mock_result = CompletionResult(
        content="pong",
        model_used="openai/gpt-4o",
        prompt_tokens=1,
        completion_tokens=1,
        cost=0.0,
        latency_ms=1,
        success=True,
    )

    latencies: list[float] = []
    errors = 0

    def one_request() -> float:
        started = time.perf_counter()
        with patch.object(engine, "complete", return_value=mock_result):
            response = client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer load-test-token"},
                json={
                    "model": "route-other",
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        return elapsed_ms

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(one_request) for _ in range(requests)]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception:
                errors += 1
    total_s = time.perf_counter() - started
    store.close()
    db_path.unlink(missing_ok=True)

    return {
        "requests": float(requests),
        "errors": float(errors),
        "total_s": total_s,
        "p50_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": (
            sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
        ),
        "rps": requests / total_s if total_s else 0.0,
    }


def _live_probe(base_url: str, token: str, concurrency: int, requests: int) -> dict[str, float]:
    """Hit GET /v1/models concurrently against a live service."""
    import httpx

    latencies: list[float] = []
    errors = 0
    headers = {"Authorization": f"Bearer {token}"}

    def one_request() -> float:
        started = time.perf_counter()
        response = httpx.get(f"{base_url.rstrip('/')}/v1/models", headers=headers, timeout=10.0)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}")
        return elapsed_ms

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(one_request) for _ in range(requests)]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception:
                errors += 1
    total_s = time.perf_counter() - started
    return {
        "requests": float(requests),
        "errors": float(errors),
        "total_s": total_s,
        "p50_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": (
            sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
        ),
        "rps": requests / total_s if total_s else 0.0,
    }


def main() -> int:
    """Run the gateway load test and print a short summary."""
    parser = argparse.ArgumentParser(description="Concurrent gateway load test")
    parser.add_argument("--concurrency", type=int, default=8, help="Worker threads")
    parser.add_argument("--requests", type=int, default=40, help="Total requests")
    parser.add_argument("--live", nargs=2, metavar=("URL", "TOKEN"), help="Live HTTP base URL")
    args = parser.parse_args()

    if args.live:
        stats = _live_probe(args.live[0], args.live[1], args.concurrency, args.requests)
        mode = "live"
    else:
        stats = _mock_client(args.concurrency, args.requests)
        mode = "mocked"

    print(f"mode:        {mode}")
    print(f"concurrency: {args.concurrency}")
    print(f"requests:    {int(stats['requests'])}")
    print(f"errors:      {int(stats['errors'])}")
    print(f"total:       {stats['total_s']:.2f}s")
    print(f"throughput:  {stats['rps']:.1f} req/s")
    print(f"latency p50: {stats['p50_ms']:.1f} ms")
    print(f"latency p95: {stats['p95_ms']:.1f} ms")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
