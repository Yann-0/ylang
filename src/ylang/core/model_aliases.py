"""Cursor model slug → LiteLLM model aliases (configurable)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CURSOR_SLUG_ALIASES: dict[str, str] = {
    "claude-4.6-sonnet-high-thinking": "anthropic/claude-sonnet-4-6",
    "claude-4.6-opus-high-thinking": "anthropic/claude-opus-4-6",
    "claude-4.6-sonnet-medium-thinking": "anthropic/claude-sonnet-4-6",
    "claude-3.5-sonnet-high-thinking": "anthropic/claude-sonnet-4-6",
    "claude-sonnet-4-5": "anthropic/claude-sonnet-4-6",
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4-6",
    "composer": "anthropic/claude-sonnet-4-6",
    "composer-2.5-fast": "anthropic/claude-sonnet-4-6",
    "gpt-5.3-codex-high-fast": "openai/gpt-4o",
    "gpt-5.5-medium": "openai/gpt-4o",
    "gemini-3.1-pro": "openai/gpt-4o",
}


def default_aliases_path() -> Path:
    """Return the bundled default aliases JSON path."""
    return Path(__file__).resolve().parents[3] / "deploy" / "ylang.models.json"


def load_cursor_slug_aliases(path: Path | None = None) -> dict[str, str]:
    """Load slug aliases from env path, explicit path, or bundled defaults."""
    aliases = dict(DEFAULT_CURSOR_SLUG_ALIASES)
    config_path = path
    if config_path is None:
        raw = os.environ.get("YLANG_MODEL_ALIASES_PATH")
        if raw:
            config_path = Path(raw)
        elif default_aliases_path().is_file():
            config_path = default_aliases_path()
    if config_path is None or not config_path.is_file():
        return aliases
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load model aliases from %s: %s", config_path, exc)
        return aliases
    if not isinstance(payload, dict):
        logger.warning("Model aliases file must be a JSON object: %s", config_path)
        return aliases
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
            aliases[key.strip()] = value.strip()
            aliases[key.strip().lower()] = value.strip()
    return aliases
