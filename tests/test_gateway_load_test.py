"""Tests for the gateway load test script."""

from __future__ import annotations

import importlib.util
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ylang.usage.store import UsageStore, open_store


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


def test_mock_gateway_load_isolates_concurrent_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent probes must own different databases and remove their directories."""
    module = _load_module()
    opened: list[Path] = []

    def recording_open(path: Path) -> UsageStore:
        """Record each real database used by the probes."""
        opened.append(path)
        return open_store(path)

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr("ylang.usage.store.open_store", recording_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(module._mock_client, concurrency=2, requests=4)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]

    assert all(result["errors"] == 0 for result in results)
    assert len(opened) == len(set(opened)) == 2
    assert all(path.is_relative_to(tmp_path) for path in opened)
    assert all(not path.parent.exists() for path in opened)


def test_mock_gateway_load_cleans_up_after_setup_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A setup failure must close SQLite and remove only that run's storage."""
    module = _load_module()
    opened: list[tuple[Path, MagicMock]] = []

    def recording_open(path: Path) -> MagicMock:
        """Wrap the real store so its closure remains observable."""
        store = MagicMock(wraps=open_store(path))
        opened.append((path, store))
        return store

    def fail_setup(*args: object, **kwargs: object) -> None:
        """Reproduce failure after the database has opened."""
        raise RuntimeError("setup failed")

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr("ylang.usage.store.open_store", recording_open)
    monkeypatch.setattr("ylang.gateway.routes.register_gateway_routes", fail_setup)
    with pytest.raises(RuntimeError, match="setup failed"):
        module._mock_client(concurrency=1, requests=1)

    assert len(opened) == 1
    path, store = opened[0]
    store.close.assert_called_once_with()
    assert path.is_relative_to(tmp_path)
    assert not path.parent.exists()
