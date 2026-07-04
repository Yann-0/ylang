"""Helpers for storing improver input samples in usage rows."""

from __future__ import annotations

_IMPROVER_INPUT_SAMPLE_MAX_LEN = 200


def truncate_improver_input_sample(text: str | None) -> str | None:
    """Truncate improver prompt text for persistence (max ~200 chars)."""
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if len(stripped) <= _IMPROVER_INPUT_SAMPLE_MAX_LEN:
        return stripped
    return stripped[: _IMPROVER_INPUT_SAMPLE_MAX_LEN - 3] + "..."
