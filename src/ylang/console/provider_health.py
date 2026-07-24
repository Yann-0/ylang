"""Provider connectivity checks for the admin console."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from ylang.settings import Settings, provider_has_key


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """Health check result for one LLM provider or Ollama."""

    name: str
    ok: bool
    detail: str


def check_providers(settings: Settings) -> list[ProviderStatus]:
    """Return configured provider key status and Ollama reachability."""
    results: list[ProviderStatus] = []
    keys = settings.provider_keys
    for provider in ("openai", "anthropic", "mistral", "perplexity"):
        value = getattr(keys, provider)
        if value:
            results.append(
                ProviderStatus(name=provider, ok=True, detail="API key configured")
            )
        else:
            results.append(
                ProviderStatus(name=provider, ok=False, detail="API key not set")
            )
    fallback_ok = provider_has_key(
        settings.fallback_model, keys
    ) or settings.fallback_model.lower().startswith("ollama/")
    results.append(
        ProviderStatus(
            name="fallback_model",
            ok=fallback_ok,
            detail=settings.fallback_model,
        )
    )
    ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    ollama_ok = _ollama_reachable(ollama_host)
    results.append(
        ProviderStatus(
            name="ollama",
            ok=ollama_ok,
            detail=f"{ollama_host} {'reachable' if ollama_ok else 'not reachable'}",
        )
    )
    return results


def _ollama_reachable(host: str) -> bool:
    parsed = urlparse(host)
    hostname = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    try:
        with socket.create_connection((hostname, port), timeout=2):
            return True
    except OSError:
        return False
