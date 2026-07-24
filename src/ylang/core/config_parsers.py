"""Shared configuration parsers for env and runtime overrides."""

from __future__ import annotations


def parse_model_list(raw: str, *, require_non_empty: bool = False) -> list[str]:
    """Split a comma-separated model list into stripped non-empty parts.

    When ``require_non_empty`` is true (env activity lists), raise ``ValueError``
    if the result is empty. Runtime overrides may pass empty to mean “ignore”.
    """
    models = [part.strip() for part in raw.split(",") if part.strip()]
    if require_non_empty and not models:
        msg = "model list env var must contain at least one model"
        raise ValueError(msg)
    return models


def parse_bool_flag(raw: str | None) -> bool | None:
    """Parse a truthy/falsy flag string; return None when unrecognized or empty."""
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if not lowered:
        return None
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None
