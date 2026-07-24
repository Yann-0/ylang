"""Read Cursor hook logs for the admin console."""

from __future__ import annotations

from pathlib import Path


def tail_hook_log(*, max_lines: int = 40) -> list[str]:
    """Return the last ``max_lines`` from the improve-prompt hook log."""
    log_path = Path.home() / ".cursor" / "hooks" / "ylang-improve-prompt.log"
    if not log_path.is_file():
        return ["(no hook log yet — submit a prompt in Cursor to generate entries)"]
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [f"(could not read hook log: {exc})"]
    if not lines:
        return ["(hook log is empty)"]
    return lines[-max_lines:]
