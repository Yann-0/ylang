"""Load prompt collection CSV from URL or local path."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PROMPTS_URL = (
    "https://raw.githubusercontent.com/f/awesome-chatgpt-prompts/main/prompts.csv"
)


def load_csv_text(*, url: str | None = None, csv_path: Path | None = None) -> str:
    """Return CSV text from a local file or remote URL."""
    if csv_path is not None:
        return csv_path.read_text(encoding="utf-8")
    target = url or DEFAULT_PROMPTS_URL
    if target.startswith("file://"):
        return Path(target.removeprefix("file://")).read_text(encoding="utf-8")
    if Path(target).exists():
        return Path(target).read_text(encoding="utf-8")
    try:
        with urllib.request.urlopen(target, timeout=60) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        msg = f"failed to fetch prompts CSV from {target}: {exc}"
        raise OSError(msg) from exc
