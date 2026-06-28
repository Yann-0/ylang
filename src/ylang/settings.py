"""Single typed settings object for ylang."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ylang.core.types import Activity

logger = logging.getLogger(__name__)

McpTransport = Literal["stdio", "http"]
ProviderName = Literal["openai", "anthropic", "mistral", "perplexity"]

_PROVIDER_ENV_VARS: dict[ProviderName, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}

_LITELLM_PREFIX_ALIASES: dict[str, ProviderName] = {
    "mistralai": "mistral",
}

DEFAULT_ACTIVITY_MODELS: dict[Activity, str] = {
    "code": "anthropic/claude-3-5-sonnet-latest",
    "search": "perplexity/sonar",
    "reason": "openai/o3-mini",
    "other": "mistral/mistral-small-latest",
}

DEFAULT_FALLBACK_MODEL: str = "ollama/qwen2.5"

_ACTIVITY_MODEL_ENV_VARS: dict[Activity, str] = {
    "code": "YLANG_MODEL_CODE",
    "search": "YLANG_MODEL_SEARCH",
    "reason": "YLANG_MODEL_REASON",
    "other": "YLANG_MODEL_OTHER",
}


class ProviderKeys(BaseModel):
    """Optional API keys for cloud LLM providers."""

    openai: str | None = Field(default=None, description="OpenAI API key.")
    anthropic: str | None = Field(default=None, description="Anthropic API key.")
    mistral: str | None = Field(default=None, description="Mistral API key.")
    perplexity: str | None = Field(default=None, description="Perplexity API key.")

    def configured_names(self) -> list[ProviderName]:
        """Return provider names that have a non-empty API key."""
        names: list[ProviderName] = []
        if self.openai:
            names.append("openai")
        if self.anthropic:
            names.append("anthropic")
        if self.mistral:
            names.append("mistral")
        if self.perplexity:
            names.append("perplexity")
        return names

    def missing_names(self) -> list[ProviderName]:
        """Return provider names with no API key configured."""
        configured = set(self.configured_names())
        return [name for name in _PROVIDER_ENV_VARS if name not in configured]

    def key_for_provider(self, provider: ProviderName) -> str | None:
        """Return the API key for a provider, or None if not configured."""
        return getattr(self, provider) or None


def provider_from_litellm_model(model: str) -> ProviderName | None:
    """Map a LiteLLM provider-prefixed model string to a known provider name."""
    if "/" not in model:
        return None
    prefix = model.split("/", 1)[0].lower()
    if prefix in _PROVIDER_ENV_VARS:
        return prefix  # type: ignore[return-value]
    return _LITELLM_PREFIX_ALIASES.get(prefix)


def requires_provider_key(model: str) -> bool:
    """Return True when the model routes through a cloud provider that needs a key."""
    provider = provider_from_litellm_model(model)
    return provider is not None


def provider_has_key(model: str, provider_keys: ProviderKeys) -> bool:
    """Return True when the model's provider is configured or does not need a key."""
    provider = provider_from_litellm_model(model)
    if provider is None:
        return True
    return provider_keys.key_for_provider(provider) is not None


def api_key_for_model(model: str, provider_keys: ProviderKeys) -> str | None:
    """Return the API key to pass to LiteLLM for a model, if one is required."""
    provider = provider_from_litellm_model(model)
    if provider is None:
        return None
    return provider_keys.key_for_provider(provider)


def resolve_available_model(
    requested: str,
    activity_models: dict[Activity, str],
    provider_keys: ProviderKeys,
    fallback_model: str,
) -> str:
    """Pick a model whose provider key is configured, or fall back safely."""
    if provider_has_key(requested, provider_keys):
        return requested

    provider = provider_from_litellm_model(requested)
    env_var = _PROVIDER_ENV_VARS.get(provider, "Provider key") if provider else "Provider key"
    logger.warning("%s is not configured; skipping model %s", env_var, requested)
    if provider is not None:
        logger.warning("Set %s to enable %s models", _PROVIDER_ENV_VARS[provider], provider)

    for candidate in activity_models.values():
        if provider_has_key(candidate, provider_keys):
            if candidate != requested:
                logger.warning("Falling back from %s to %s", requested, candidate)
            return candidate

    if provider_has_key(fallback_model, provider_keys):
        logger.warning("Falling back from %s to %s", requested, fallback_model)
        return fallback_model

    return fallback_model


def effective_activity_models(
    activity_models: dict[Activity, str],
    provider_keys: ProviderKeys,
    fallback_model: str,
) -> dict[Activity, str]:
    """Return the activity map after applying provider-key availability rules."""
    return {
        activity: resolve_available_model(
            model,
            activity_models,
            provider_keys,
            fallback_model,
        )
        for activity, model in activity_models.items()
    }


class Settings(BaseModel):
    """Application configuration loaded from environment variables."""

    storage_path: Path = Field(
        default=Path("~/.ylang/ylang.db"),
        description="Local SQLite database path.",
    )
    transport: McpTransport = Field(
        default="stdio",
        description="MCP transport: stdio (local subprocess) or http (streamable HTTP).",
    )
    host: str = Field(
        default="0.0.0.0",
        description="Bind host when transport is http.",
    )
    port: int = Field(
        default=8787,
        ge=1,
        le=65535,
        description="Bind port when transport is http.",
    )
    auth_token: str | None = Field(
        default=None,
        description="Bearer token required for http transport.",
    )
    provider_keys: ProviderKeys = Field(
        default_factory=ProviderKeys,
        description="Optional LLM provider API keys.",
    )
    activity_models: dict[Activity, str] = Field(
        default_factory=lambda: dict(DEFAULT_ACTIVITY_MODELS),
        description="Activity to LiteLLM model routing map.",
    )
    fallback_model: str = Field(
        default=DEFAULT_FALLBACK_MODEL,
        description="LiteLLM fallback model when the primary route fails.",
    )

    @classmethod
    def load(cls) -> Settings:
        """Build settings from environment variables and defaults."""
        kwargs: dict[str, object] = {}

        raw_path = os.environ.get("YLANG_STORAGE_PATH")
        if raw_path is not None:
            kwargs["storage_path"] = Path(raw_path)

        if raw_transport := os.environ.get("YLANG_TRANSPORT"):
            kwargs["transport"] = raw_transport

        if raw_host := os.environ.get("YLANG_HOST"):
            kwargs["host"] = raw_host

        if raw_port := os.environ.get("YLANG_PORT"):
            kwargs["port"] = int(raw_port)

        if raw_token := os.environ.get("YLANG_AUTH_TOKEN"):
            kwargs["auth_token"] = raw_token

        provider_keys = _load_provider_keys()
        kwargs["provider_keys"] = provider_keys
        kwargs["activity_models"] = _load_activity_models()
        if raw_fallback := os.environ.get("YLANG_FALLBACK_MODEL"):
            kwargs["fallback_model"] = raw_fallback

        settings = cls(**kwargs)
        _warn_missing_provider_keys(provider_keys)
        return settings

    def resolved_storage_path(self) -> Path:
        """Return the expanded, absolute storage path."""
        return self.storage_path.expanduser().resolve()

    def effective_activity_models(self) -> dict[Activity, str]:
        """Return the activity map that will be used given configured provider keys."""
        return effective_activity_models(
            self.activity_models,
            self.provider_keys,
            self.fallback_model,
        )

    def log_llm_config(self) -> None:
        """Log configured LLM providers and the active activity model map to stderr."""
        configured = self.provider_keys.configured_names()
        missing = self.provider_keys.missing_names()
        effective = self.effective_activity_models()

        print("  llm providers configured:", file=sys.stderr)
        if configured:
            print(f"    {', '.join(configured)}", file=sys.stderr)
        else:
            print("    (none)", file=sys.stderr)

        if missing:
            print("  llm providers not configured:", file=sys.stderr)
            print(f"    {', '.join(missing)}", file=sys.stderr)

        print("  activity models:", file=sys.stderr)
        for activity in ("code", "search", "reason", "other"):
            print(f"    {activity}: {effective[activity]}", file=sys.stderr)


def _read_optional_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _load_provider_keys() -> ProviderKeys:
    return ProviderKeys(
        openai=_read_optional_env("OPENAI_API_KEY"),
        anthropic=_read_optional_env("ANTHROPIC_API_KEY"),
        mistral=_read_optional_env("MISTRAL_API_KEY"),
        perplexity=_read_optional_env("PERPLEXITY_API_KEY"),
    )


def _load_activity_models() -> dict[Activity, str]:
    models = dict(DEFAULT_ACTIVITY_MODELS)
    for activity, env_var in _ACTIVITY_MODEL_ENV_VARS.items():
        if override := _read_optional_env(env_var):
            models[activity] = override
    return models


def _warn_missing_provider_keys(provider_keys: ProviderKeys) -> None:
    for provider in provider_keys.missing_names():
        logger.warning(
            "%s not set; %s models will not be routed",
            _PROVIDER_ENV_VARS[provider],
            provider,
        )
