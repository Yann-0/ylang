"""Canonical usage activity labels for consistent aggregation and pattern detection."""

from __future__ import annotations

_CANONICAL_IMPROVE_MODES: frozenset[str] = frozenset(
    {"agent", "plan", "debug", "ask", "multitask"}
)

_IMPROVE_SUFFIX_ALIASES: dict[str, str] = {
    "agent": "agent",
    "cursor": "agent",
    "cursor-agent": "agent",
    "cursor_agent": "agent",
    "implementation": "agent",
    "plan": "plan",
    "planning": "plan",
    "plan-mode": "plan",
    "plan_mode": "plan",
    "debug": "debug",
    "debug-mode": "debug",
    "debug_mode": "debug",
    "troubleshoot": "debug",
    "ask": "ask",
    "ask-mode": "ask",
    "ask_mode": "ask",
    "question": "ask",
    "multitask": "multitask",
    "multitask-mode": "multitask",
    "multitask_mode": "multitask",
    "multi-task": "multitask",
}


def normalize_usage_activity(activity: str) -> str:
    """Return a stable lowercase activity label for usage rows.

    ``improve:*`` suffixes are mapped to canonical Cursor modes (e.g.
    ``improve:Cursor`` and ``improve:cursor-agent`` → ``improve:agent``).
    Unknown ``improve:`` suffixes (e.g. tool names) are lowercased only.
    """
    trimmed = activity.strip()
    if not trimmed:
        return trimmed
    if not trimmed.startswith("improve:"):
        return trimmed.lower()
    suffix = trimmed.removeprefix("improve:")
    key = suffix.strip().lower().replace(" ", "-")
    if key in _CANONICAL_IMPROVE_MODES:
        mode = key
    elif key in _IMPROVE_SUFFIX_ALIASES:
        mode = _IMPROVE_SUFFIX_ALIASES[key]
    else:
        mode = key
    return f"improve:{mode}"
