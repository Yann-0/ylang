"""Compatibility mappings from client/legacy model slugs to LiteLLM routes.

An alias does **not** assert that the requested identifier is the same model as
the resolved route. It means: accept this historical or client-specific name
and resolve it to a currently supported LiteLLM ``provider/model`` string.

Canonical defaults live in ``DEFAULT_CURSOR_SLUG_ALIASES``.
``deploy/ylang.models.json`` is an operator overlay merged on top; overlapping
keys must match the Python defaults (enforced by tests).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ylang.core.types import ExplicitModelLookup

logger = logging.getLogger(__name__)

DEFAULT_CURSOR_SLUG_ALIASES: dict[str, str] = {
    "claude-4.6-sonnet-high-thinking": "anthropic/claude-sonnet-5",
    "claude-4.6-opus-high-thinking": "anthropic/claude-opus-5",
    "claude-4.6-sonnet-medium-thinking": "anthropic/claude-sonnet-5",
    "claude-3.5-sonnet-high-thinking": "anthropic/claude-sonnet-5",
    "claude-sonnet-4-5": "anthropic/claude-sonnet-5",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-5",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
    "claude-opus-5": "anthropic/claude-opus-5",
    "composer": "anthropic/claude-sonnet-5",
    "composer-2.5-fast": "anthropic/claude-sonnet-5",
    # Codex is Responses-API only; chat/gateway uses the GPT policy default.
    "gpt-5.3-codex-high-fast": "openai/gpt-5.5",
    "gpt-5.5-medium": "openai/gpt-5.5",
    # Cursor still sends 3.1-pro; compatibility-map to the tested Gemini default.
    "gemini-3.1-pro": "gemini/gemini-3.7-flash",
    # Local Ollama tag ``gpt-4o-mini`` collides with OpenAI's model id; LiteLLM
    # misroutes ``ollama/gpt-4o-mini`` through the OpenAI client. Use the
    # non-colliding parent tag (same weights on this host).
    "gpt-4o-mini": "ollama/qwen-coder-14b",
    "ollama/gpt-4o-mini": "ollama/qwen-coder-14b",
    # Prefer this custom Cursor model id — built-in ``gpt-4o-mini`` is often
    # intercepted and sent to api.openai.com (BYOK rate-limit errors).
    "ylang-mini": "ollama/qwen-coder-14b",
}

# Prefix compatibility rules applied when no exact alias matches.
_PREFIX_COMPATIBILITY: tuple[tuple[tuple[str, ...], str], ...] = (
    (("claude-sonnet-4-", "claude-sonnet-5-"), "anthropic/claude-sonnet-5"),
    (("claude-opus-4-", "claude-opus-5-"), "anthropic/claude-opus-5"),
    (("claude-fable-",), "anthropic/claude-fable-5"),
)

AUTO_MODEL_SENTINELS: frozenset[str] = frozenset({"", "auto", "default", "route"})

# Keys whose overlay value differs from ``DEFAULT_CURSOR_SLUG_ALIASES`` (or are new).
_LOADED_OVERLAY_KEYS: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CompatibilityAliasHit:
    """One compatibility mapping from a client/legacy slug to a LiteLLM route."""

    requested_alias: str
    resolved_model: str
    source: Literal["builtin", "overlay", "prefix"]


def default_aliases_path() -> Path:
    """Return the bundled default aliases JSON path."""
    return Path(__file__).resolve().parents[3] / "deploy" / "ylang.models.json"


def loaded_overlay_alias_keys() -> frozenset[str]:
    """Return alias keys remapped or added by the last overlay load."""
    return _LOADED_OVERLAY_KEYS


def load_cursor_slug_aliases(path: Path | None = None) -> dict[str, str]:
    """Load slug aliases from env path, explicit path, or bundled defaults.

    Overlay keys that add or remap a Python default are logged. Identical
    values are silent no-ops so the bundled JSON can mirror Python exactly.
    """
    global _LOADED_OVERLAY_KEYS
    aliases = dict(DEFAULT_CURSOR_SLUG_ALIASES)
    overlay_keys: set[str] = set()
    config_path = path
    if config_path is None:
        raw = os.environ.get("YLANG_MODEL_ALIASES_PATH")
        if raw:
            config_path = Path(raw)
        elif default_aliases_path().is_file():
            config_path = default_aliases_path()
    if config_path is None or not config_path.is_file():
        _LOADED_OVERLAY_KEYS = frozenset()
        return aliases
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load model aliases from %s: %s", config_path, exc)
        _LOADED_OVERLAY_KEYS = frozenset()
        return aliases
    if not isinstance(payload, dict):
        logger.warning("Model aliases file must be a JSON object: %s", config_path)
        _LOADED_OVERLAY_KEYS = frozenset()
        return aliases
    for key, value in payload.items():
        if not (
            isinstance(key, str)
            and isinstance(value, str)
            and key.strip()
            and value.strip()
        ):
            continue
        stripped_key = key.strip()
        stripped_value = value.strip()
        previous = DEFAULT_CURSOR_SLUG_ALIASES.get(stripped_key)
        if previous is None:
            logger.info(
                "Alias overlay %s adds compatibility mapping %r -> %r",
                config_path,
                stripped_key,
                stripped_value,
            )
            overlay_keys.add(stripped_key)
            overlay_keys.add(stripped_key.lower())
        elif previous != stripped_value:
            logger.info(
                "Alias overlay %s remaps %r from %r to %r "
                "(compatibility mapping, not identity)",
                config_path,
                stripped_key,
                previous,
                stripped_value,
            )
            overlay_keys.add(stripped_key)
            overlay_keys.add(stripped_key.lower())
        aliases[stripped_key] = stripped_value
        aliases[stripped_key.lower()] = stripped_value
    _LOADED_OVERLAY_KEYS = frozenset(overlay_keys)
    return aliases


def lookup_compatibility_alias(
    model: str,
    aliases: dict[str, str] | None = None,
    *,
    overlay_keys: frozenset[str] | None = None,
) -> CompatibilityAliasHit | None:
    """Return a compatibility hit, or None when the slug is not an alias.

    Exact table hits win. Prefix rules run only when no table entry matches.
    ``source`` is ``overlay`` only when the overlay remapped or added the key.
    """
    stripped = model.strip()
    if not stripped:
        return None
    table = aliases if aliases is not None else DEFAULT_CURSOR_SLUG_ALIASES
    remapped = overlay_keys if overlay_keys is not None else _LOADED_OVERLAY_KEYS
    mapped = table.get(stripped) or table.get(stripped.lower())
    if mapped:
        source: Literal["builtin", "overlay", "prefix"] = (
            "overlay"
            if stripped in remapped or stripped.lower() in remapped
            else "builtin"
        )
        return CompatibilityAliasHit(
            requested_alias=stripped,
            resolved_model=mapped,
            source=source,
        )
    lowered = stripped.lower()
    for prefixes, target in _PREFIX_COMPATIBILITY:
        if lowered.startswith(prefixes):
            return CompatibilityAliasHit(
                requested_alias=stripped,
                resolved_model=target,
                source="prefix",
            )
    return None


def classify_explicit_model(
    model: str,
    *,
    aliases: dict[str, str] | None = None,
    is_routable: Callable[[str], bool],
) -> ExplicitModelLookup:
    """Classify a client model string as alias, explicit LiteLLM, or deferral.

    ``is_routable`` is the caller's LiteLLM-routable predicate so this module
    does not import provider-key helpers.
    """
    stripped = model.strip()
    if stripped.lower() in AUTO_MODEL_SENTINELS:
        return ExplicitModelLookup(
            requested=stripped,
            resolved=None,
            requested_alias=None,
            reason="activity_default",
        )
    hit = lookup_compatibility_alias(stripped, aliases)
    if hit is not None:
        return ExplicitModelLookup(
            requested=stripped,
            resolved=hit.resolved_model,
            requested_alias=hit.requested_alias,
            reason="compatibility_alias",
            alias_source=hit.source,
        )
    if is_routable(stripped):
        return ExplicitModelLookup(
            requested=stripped,
            resolved=stripped,
            requested_alias=None,
            reason="explicit_model",
        )
    logger.warning(
        "Ignoring non-LiteLLM model slug %r; using activity routing instead",
        model,
    )
    return ExplicitModelLookup(
        requested=stripped,
        resolved=None,
        requested_alias=None,
        reason="activity_default",
    )
