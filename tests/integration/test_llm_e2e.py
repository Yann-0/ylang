"""Optional smoke tests against a live Ollama instance (``@pytest.mark.llm_e2e``)."""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest

from ylang.core.engine import Engine
from ylang.core.model_router import ModelRouter
from ylang.settings import ProviderKeys
from ylang.usage.store import open_store

pytestmark = pytest.mark.llm_e2e


def _ollama_reachable() -> bool:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    parsed = urlparse(host)
    hostname = parsed.hostname or "localhost"
    port = parsed.port or 11434
    try:
        with socket.create_connection((hostname, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture
def ollama_engine(tmp_path: object) -> Engine:
    if not _ollama_reachable():
        pytest.skip("OLLAMA_HOST not reachable")
    store = open_store(tmp_path / "llm-e2e.db")  # type: ignore[operator]
    router = ModelRouter(
        activity_model_lists={"other": ["ollama/qwen2.5"]},
        provider_keys=ProviderKeys(),
        fallback_model="ollama/qwen2.5",
    )
    return Engine(store, surface="e2e", router=router)


def test_gateway_completion_against_ollama(ollama_engine: Engine) -> None:
    """Smoke: complete a short prompt via Ollama/qwen2.5."""
    result = ollama_engine.complete(
        [{"role": "user", "content": "Reply with exactly: pong"}],
        "other",
        model="ollama/qwen2.5",
    )
    if not result.success:
        pytest.skip(f"Ollama model unavailable: {result.error}")
    assert result.content.strip()
