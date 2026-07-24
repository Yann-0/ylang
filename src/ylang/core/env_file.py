"""Discover and load Ylang environment files for CLI and MCP startup."""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def env_file_candidates() -> list[Path]:
    """Return env file paths to try, highest priority first."""
    candidates: list[Path] = []
    if raw := os.environ.get("YLANG_ENV_FILE"):
        candidates.append(Path(raw).expanduser())
    candidates.append(Path("/srv/ylang/ylang.env"))
    pkg_root = Path(__file__).resolve().parents[2]
    candidates.append(pkg_root.parent / "ylang.env")
    candidates.append(Path.home() / ".config" / "ylang" / "ylang.env")
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse a single ``KEY=VALUE`` or ``export KEY=VALUE`` line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = _ENV_LINE.match(stripped)
    if match is None:
        return None
    key, raw_value = match.group(1), match.group(2)
    return key, _unquote_env_value(raw_value.strip())


def _unquote_env_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    return raw


def load_env_file(path: Path, *, override: bool = False) -> bool:
    """Load variables from a shell-style env file into ``os.environ``.

    Returns ``True`` when the file existed and was read.
    """
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return False
    for line in resolved.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
    return True


def load_discovered_env_file() -> Path | None:
    """Load the first readable env file from :func:`env_file_candidates`."""
    for candidate in env_file_candidates():
        if load_env_file(candidate):
            return candidate
    return None
