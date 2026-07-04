"""Tests for the gateway load test script."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "gateway_load_test.py"
    spec = importlib.util.spec_from_file_location("gateway_load_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mock_gateway_load_completes_without_errors() -> None:
    module = _load_module()
    stats = module._mock_client(concurrency=4, requests=8)
    assert stats["errors"] == 0
    assert stats["requests"] == 8
    assert stats["rps"] > 0
