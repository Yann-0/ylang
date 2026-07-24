"""Tests for automatic env file discovery and loading."""

from __future__ import annotations

import os
from pathlib import Path

from ylang.core.env_file import (
    env_file_candidates,
    load_discovered_env_file,
    load_env_file,
    parse_env_line,
)
from ylang.settings import Settings


def test_parse_env_line_skips_comments_and_blank_lines() -> None:
    assert parse_env_line("# comment") is None
    assert parse_env_line("") is None
    assert parse_env_line("  ") is None


def test_parse_env_line_handles_export_and_quotes() -> None:
    assert parse_env_line('export YLANG_PORT=8787') == ("YLANG_PORT", "8787")
    assert parse_env_line('YLANG_HOST="0.0.0.0"') == ("YLANG_HOST", "0.0.0.0")
    assert parse_env_line("OPENAI_API_KEY='sk-test'") == ("OPENAI_API_KEY", "sk-test")


def test_load_env_file_does_not_override_existing(monkeypatch, tmp_path: Path) -> None:
    env_path = tmp_path / "ylang.env"
    env_path.write_text(
        "YLANG_STORAGE_PATH=/from/file\nYLANG_PORT=9999\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("YLANG_STORAGE_PATH", "/from/env")
    monkeypatch.delenv("YLANG_PORT", raising=False)

    assert load_env_file(env_path) is True
    assert os.environ["YLANG_STORAGE_PATH"] == "/from/env"
    assert os.environ["YLANG_PORT"] == "9999"


def test_load_discovered_env_file_uses_custom_path(
    monkeypatch, tmp_path: Path
) -> None:
    env_path = tmp_path / "custom.env"
    env_path.write_text(
        f"YLANG_STORAGE_PATH={tmp_path / 'db' / 'ylang.db'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("YLANG_ENV_FILE", str(env_path))
    monkeypatch.delenv("YLANG_STORAGE_PATH", raising=False)

    loaded = load_discovered_env_file()
    assert loaded == env_path.resolve()
    assert os.environ["YLANG_STORAGE_PATH"] == str(tmp_path / "db" / "ylang.db")


def test_settings_load_uses_discovered_env_file(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "ylang.db"
    env_path = tmp_path / "ylang.env"
    env_path.write_text(f"YLANG_STORAGE_PATH={db_path}\n", encoding="utf-8")
    monkeypatch.setenv("YLANG_ENV_FILE", str(env_path))
    monkeypatch.delenv("YLANG_STORAGE_PATH", raising=False)

    settings = Settings.load()
    assert settings.resolved_storage_path() == db_path.resolve()


def test_env_file_candidates_deduplicates_workspace_path() -> None:
    candidates = env_file_candidates()
    assert len(candidates) == len(set(candidates))
