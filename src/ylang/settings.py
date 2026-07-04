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

DEFAULT_ACTIVITY_MODEL_LISTS: dict[Activity, list[str]] = {
    "code": [
        "anthropic/claude-3-5-sonnet-latest",
        "openai/o3-mini",
        "openai/gpt-4o",
        "mistral/mistral-large-latest",
    ],
    "search": [
        "perplexity/sonar",
        "openai/gpt-4o",
        "anthropic/claude-3-5-sonnet-latest",
    ],
    "reason": [
        "openai/o3-mini",
        "anthropic/claude-3-5-sonnet-latest",
        "openai/gpt-4o",
    ],
    "improve": [
        "anthropic/claude-3-5-sonnet-latest",
        "openai/gpt-4o",
        "mistral/mistral-small-latest",
    ],
    "other": [
        "mistral/mistral-small-latest",
        "openai/gpt-4o-mini",
        "anthropic/claude-3-5-sonnet-latest",
    ],
}

DEFAULT_ACTIVITY_MODELS: dict[Activity, str] = {
    activity: models[0] for activity, models in DEFAULT_ACTIVITY_MODEL_LISTS.items()
}

DEFAULT_QUALITY_BAND: int = 0
DEFAULT_FALLBACK_MODEL: str = "ollama/qwen2.5"
DEFAULT_PROVIDER_COOLDOWN_SECONDS: int = 60

_ACTIVITY_MODEL_LIST_ENV_VARS: dict[Activity, str] = {
    "code": "YLANG_MODELS_CODE",
    "search": "YLANG_MODELS_SEARCH",
    "reason": "YLANG_MODELS_REASON",
    "improve": "YLANG_MODELS_IMPROVE",
    "other": "YLANG_MODELS_OTHER",
}

_LEGACY_ACTIVITY_MODEL_ENV_VARS: dict[Activity, str] = {
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
    activity_model_lists: dict[Activity, list[str]] = Field(
        default_factory=lambda: {
            activity: list(models) for activity, models in DEFAULT_ACTIVITY_MODEL_LISTS.items()
        },
        description="Activity to quality-ordered LiteLLM model candidate lists.",
    )
    quality_band: int = Field(
        default=DEFAULT_QUALITY_BAND,
        ge=0,
        description="Rank offset within which cost tie-break may prefer a cheaper model.",
    )
    fallback_model: str = Field(
        default=DEFAULT_FALLBACK_MODEL,
        description="Local LiteLLM floor model when cloud routes fail or are unavailable.",
    )
    provider_cooldown_seconds: int = Field(
        default=DEFAULT_PROVIDER_COOLDOWN_SECONDS,
        ge=0,
        description="Seconds to skip a provider after a retryable LLM failure.",
    )
    daily_budget_usd: float | None = Field(
        default=None,
        ge=0,
        description="Optional rolling 24h spend cap; models skipped when budget exceeded.",
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
        kwargs["activity_model_lists"] = _load_activity_model_lists()
        if raw_band := os.environ.get("YLANG_QUALITY_BAND"):
            kwargs["quality_band"] = int(raw_band)
        if raw_fallback := os.environ.get("YLANG_FALLBACK_MODEL"):
            kwargs["fallback_model"] = raw_fallback
        if raw_cooldown := os.environ.get("YLANG_PROVIDER_COOLDOWN_SECONDS"):
            kwargs["provider_cooldown_seconds"] = int(raw_cooldown)
        if raw_budget := os.environ.get("YLANG_DAILY_BUDGET_USD"):
            kwargs["daily_budget_usd"] = float(raw_budget)

        settings = cls(**kwargs)
        _warn_missing_provider_keys(provider_keys)
        return settings

    def resolved_storage_path(self) -> Path:
        """Return the expanded, absolute storage path."""
        return self.storage_path.expanduser().resolve()

    def log_llm_config(self, router: object | None = None) -> None:
        """Log configured LLM providers and active per-activity routing to stderr."""
        from ylang.core.model_router import ModelRouter

        if router is None:
            router = ModelRouter.from_settings(self)
        configured = self.provider_keys.configured_names()
        missing = self.provider_keys.missing_names()

        print("  llm providers configured:", file=sys.stderr)
        if configured:
            print(f"    {', '.join(configured)}", file=sys.stderr)
        else:
            print("    (none)", file=sys.stderr)

        if missing:
            print("  llm providers not configured:", file=sys.stderr)
            print(f"    {', '.join(missing)}", file=sys.stderr)

        print(getattr(router, "format_routing_report")(), file=sys.stderr)


def _read_optional_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _parse_model_list(raw: str) -> list[str]:
    models = [part.strip() for part in raw.split(",") if part.strip()]
    if not models:
        msg = "model list env var must contain at least one model"
        raise ValueError(msg)
    return models


def _load_provider_keys() -> ProviderKeys:
    return ProviderKeys(
        openai=_read_optional_env("OPENAI_API_KEY"),
        anthropic=_read_optional_env("ANTHROPIC_API_KEY"),
        mistral=_read_optional_env("MISTRAL_API_KEY"),
        perplexity=_read_optional_env("PERPLEXITY_API_KEY"),
    )


def _load_activity_model_lists() -> dict[Activity, list[str]]:
    from ylang.core.model_router import normalize_model_list

    lists = {
        activity: list(models) for activity, models in DEFAULT_ACTIVITY_MODEL_LISTS.items()
    }
    for activity, env_var in _ACTIVITY_MODEL_LIST_ENV_VARS.items():
        if override := _read_optional_env(env_var):
            lists[activity] = _parse_model_list(override)
    for activity, env_var in _LEGACY_ACTIVITY_MODEL_ENV_VARS.items():
        if _read_optional_env(_ACTIVITY_MODEL_LIST_ENV_VARS[activity]):
            continue
        if override := _read_optional_env(env_var):
            logger.warning(
                "%s is deprecated; use %s with a comma-separated list",
                env_var,
                _ACTIVITY_MODEL_LIST_ENV_VARS[activity],
            )
            lists[activity] = [override]
    return {activity: normalize_model_list(models) for activity, models in lists.items()}


def _warn_missing_provider_keys(provider_keys: ProviderKeys) -> None:
    for provider in provider_keys.missing_names():
        logger.warning(
            "%s not set; %s models will not be routed",
            _PROVIDER_ENV_VARS[provider],
            provider,
        )
