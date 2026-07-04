"""Detect file/terminal pointer prompts that should pass through unchanged."""

from __future__ import annotations

import re

_FILE_EXT = r"(?:txt|md|log|py|ts|tsx|js|json|yaml|yml|mdc)"
_LINE_SUFFIX = r"(?::\d+(?:-\d+)?|\s*\(\d+(?:-\d+)?\))"

_FILE_REF_RE = re.compile(
    rf"@?[\w.\\:/-]+\.{_FILE_EXT}{_LINE_SUFFIX}?",
    re.IGNORECASE,
)

_FILE_REF_SCRUB_RE = re.compile(
    rf"@?[\w.\\:/-]+\.{_FILE_EXT}{_LINE_SUFFIX}?",
    re.IGNORECASE,
)

_TASK_VERB_RE = re.compile(
    r"\b(?:fix|add|implement|update|remove|refactor|debug|create|write|change|make)\b",
    re.IGNORECASE,
)


def scrub_file_reference_numbers(text: str) -> str:
    """Remove numeric literals embedded in file/line references."""
    return _FILE_REF_SCRUB_RE.sub("", text)


def is_reference_only_prompt(text: str) -> bool:
    """Return True when the prompt is only a file/terminal pointer without a task."""
    stripped = text.strip()
    if not stripped:
        return False
    if _TASK_VERB_RE.search(stripped):
        return False
    if not _FILE_REF_RE.search(stripped):
        return False
    remainder = _FILE_REF_RE.sub("", stripped).strip(" :@\\")
    return not remainder
