"""Minimal YAML-ish frontmatter parsing for markdown adapters."""

from __future__ import annotations

import re
from typing import Any

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def parse_simple_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-ish frontmatter without a YAML dependency."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    meta: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        raw_value = value.strip()
        meta[key] = _parse_scalar(raw_value)
    body = text[match.end() :]
    return meta, body


def _parse_scalar(raw: str) -> Any:
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(part.strip()) for part in inner.split(",") if part.strip()]
    return _strip_quotes(raw)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
        return value[1:-1]
    return value